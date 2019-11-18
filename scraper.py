#!/usr/bin/env python3
"""Download all of the scores from code-golf.io and create a spreadsheet showing how the proposed
Bayesian scoring method will affect things."""

import json
import os
import sqlite3
from argparse import ArgumentParser
from datetime import datetime
from dataclasses import dataclass
from math import ceil, floor, isclose
from time import time
from typing import Dict, List

import requests
import xlsxwriter

DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass
class LeaderboardEntry:
    """Represents a score as it appears on a leaderboard."""
    user: str
    lang: str
    points: int
    rank: int
    holes: int
    strokes: int
    submitted: str


@dataclass
class SolutionInfo:
    """Represents a solution to a hole."""
    user: str
    lang: str
    hole: str
    strokes: int
    submitted: str


def get_file_path(name: str) -> str:
    """Get a local path for caching a json file."""
    return os.path.join(DIR, 'scores', f'{name}.json')

def get_from_web() -> List[Dict]:
    """Get list of solutions from the web."""
    text = requests.get('https://code-golf.io/scores/all-holes/all-langs/all').content.decode()
    # Write the data to two files, one of which has the timestamp in its name.
    timestamp = datetime.now().isoformat(timespec='seconds').replace(':', '-')
    with open(get_file_path(timestamp), 'w', encoding='utf-8') as file:
        file.write(text)
    with open(get_file_path('all'), 'w', encoding='utf-8') as file:
        file.write(text)
    return json.loads(text)


def get_from_file() -> List[Dict]:
    """Get list of solutions from a local file."""
    with open(get_file_path('all'), 'r', encoding='utf-8') as file:
        return json.load(file)


def get_all_solutions(use_local_cache) -> List[SolutionInfo]:
    """Get the user, language, character count, score, rank, and sort index for each solution."""
    if use_local_cache:
        scores = get_from_file()
    else:
        scores = get_from_web()

    return [SolutionInfo(user=item['login'], hole=item['hole'], lang=item['lang'],
                         strokes=int(item['strokes']), submitted=item['submitted'])
            for item in scores]


def make_database(cursor, all_solutions: List[SolutionInfo]):
    """Put all of the solutions into a database for easy querying."""
    cursor.execute('''create table solutions
        (hole text, user text, lang text, strokes int, submitted text,
         primary key (hole, user, lang))''')
    cursor.execute('''create view m_values as
        select
            lang,
            2.0 * NLang / Nmax + 1 as M
          from (
            select lang, count(*) as NLang from solutions group by lang
          )
          cross join (
            select count(*) as Nmax from solutions group by lang order by count(*) desc limit 1
          )''')
    cursor.execute('''create view bayesian as
        select
            t1.lang,
            t1.hole,
            N,
            M,
            S,
            Sa,
            (N / (N + M)) * S + (M / (N + M)) * Sa as Sb
          from (
            select lang, hole, count(*) as N, min(strokes) as S
            from solutions
            group by lang, hole
          ) as t1
          inner join (
            select hole, min(strokes) as Sa from solutions group by hole
          ) as t2
            on t1.hole = t2.hole
          inner join m_values
          on t1.lang = m_values.lang''')
    cursor.execute('''create view scores as
        select
            user,
            hole,
            lang,
            N,
            M,
            S,
            Sa,
            Sb,
            strokes,
            1000 * Sb / strokes as new_score,
            submitted
          from solutions
          inner join bayesian using(lang, hole)''')
    cursor.execute('''create view total_scores as
        select
            user,
            sum(new_score) as total_score,
            count(*) as holes,
            sum(strokes) as strokes
          from (
            select
                user,
                hole,
                min(strokes) as strokes,
                max(new_score) as new_score
              from scores
              group by user, hole
          )
          group by user''')
    data = [(s.hole, s.user, s.lang, s.strokes, s.submitted) for s in all_solutions]
    cursor.executemany('INSERT INTO solutions (hole, user, lang, strokes, submitted) '
                       'VALUES (?,?,?,?,?)', data)


def get_overall_leaderboard(cursor, lang='all-langs') -> List[LeaderboardEntry]:
    """Get leaderboard entries for the overall leaderboard."""
    # sqlite doesn't support PostgreSQL's DISTINCT ON.
    query = '''
        WITH augmented_solutions AS (
          SELECT hole,
                 user,
                 strokes,
                 submitted,
                 ROW_NUMBER() OVER (PARTITION BY hole, user
                                    ORDER BY strokes, submitted) hole_user_ordinal
            FROM solutions
           WHERE ? IN ('all-langs', lang)
        ), leaderboard AS (
          SELECT hole,
                 user,
                 strokes,
                 submitted
            FROM augmented_solutions
           WHERE hole_user_ordinal = 1
        ), scored_leaderboard AS (
          SELECT hole,
                 ROUND(
                     (COUNT(*) OVER (PARTITION BY hole) -
                        RANK() OVER (PARTITION BY hole ORDER BY strokes) + 1)
                     * (1000.0 / COUNT(*) OVER (PARTITION BY hole))
                 ) points,
                 strokes,
                 submitted,
                 user
            FROM leaderboard
        ), summed_leaderboard AS (
          SELECT user,
                 COUNT(*)       holes,
                 SUM(points)    points,
                 SUM(strokes)   strokes,
                 MAX(submitted) submitted
            FROM scored_leaderboard
        GROUP BY user
        ) SELECT user,
                 '' lang,
                 points,
                 RANK() OVER (ORDER BY points DESC, strokes),
                 holes,
                 strokes,
                 submitted
            FROM summed_leaderboard
        ORDER BY points DESC, strokes, submitted'''
    return [LeaderboardEntry(*item) for item in cursor.execute(query, [lang])]


def get_leaderboard(cursor, hole='all-holes', lang='all-langs') -> List[LeaderboardEntry]:
    """Get leaderboard entries for a hole or for the overall leaderboard."""
    if hole == 'all-holes':
        return get_overall_leaderboard(cursor, lang)
    query = '''
        WITH leaderboard AS (
          SELECT hole,
                 submitted,
                 strokes,
                 user,
                 lang
            FROM solutions
           WHERE hole = ?
             AND ? IN ('all-langs', lang)
        ), scored_leaderboard AS (
          SELECT hole,
                 ROUND(
                     (COUNT(*) OVER (PARTITION BY hole) -
                        RANK() OVER (PARTITION BY hole ORDER BY strokes) + 1)
                     * (1000.0 / COUNT(*) OVER (PARTITION BY hole))
                 ) points,
                 strokes,
                 submitted,
                 user,
                 lang
            FROM leaderboard
        ) SELECT user,
                 lang,
                 points,
                 RANK() OVER (ORDER BY points DESC, strokes),
                 1 holes,
                 strokes,
                 submitted
            FROM scored_leaderboard
        ORDER BY points DESC, strokes, submitted'''
    return [LeaderboardEntry(*item) for item in cursor.execute(query, [hole, lang])]


def get_column_reference(headers, name):
    """Make an Excel-style column reference."""
    return chr(ord('A') + headers.index(name))


def get_column_range_reference(headers, name):
    """Make an Excel-style column range reference for a single column."""
    reference = get_column_reference(headers, name)
    return f'{reference}:{reference}'


def write_all_holes_worksheet(cursor, worksheet, formats): # pylint: disable=too-many-locals
    """Write a worksheet for all-holes."""
    worksheet.freeze_panes(1, 0)
    headers = ['User', 'New Score', 'New Rank', 'Old Score', 'Old Rank', 'Δ Score', 'Δ Rank',
               'Strokes', 'Holes', 'Strokes/Hole']
    # set column width
    worksheet.set_column(get_column_range_reference(headers, 'User'), 22)
    worksheet.set_column(get_column_range_reference(headers, 'Strokes/Hole'), 11)
    for index, item in enumerate(headers):
        worksheet.write(0, index, item)

    results = list(cursor.execute('''
        SELECT user,
               total_score,
               holes,
               strokes,
               RANK() OVER (ORDER BY total_score DESC) rank
          FROM total_scores
      ORDER BY total_score DESC'''))

    old_results = {entry.user: entry for entry in get_leaderboard(cursor)}

    for index, item in enumerate(results):
        user = item[0]
        total_score = item[1]
        holes = item[2]
        strokes = item[3]
        rank = item[4]
        old_entry = old_results[user]
        assert old_entry.user == user and old_entry.holes == holes and old_entry.strokes == strokes
        data = [user, total_score, rank, old_entry.points, old_entry.rank, 0, 0, strokes, holes]
        for column_index, column in enumerate(data):
            worksheet.write(index + 1, column_index, column, formats.get(headers[column_index]))

        def get_reference(name):
            return get_column_reference(headers, name) + str(index + 2)
        def set_column_value(name, value):
            worksheet.write(index + 1, headers.index(name), value, formats[name])

        set_column_value('Δ Score', f'={get_reference("New Score")}-{get_reference("Old Score")}')
        set_column_value('Δ Rank', f'={get_reference("New Rank")}-{get_reference("Old Rank")}')
        set_column_value('Strokes/Hole', f'={get_reference("Strokes")}/{get_reference("Holes")}')


def floor_with_tolerance(num):
    """Acts like floor, but rounds up if num is close to the next highest integer."""
    if isclose(num, ceil(num)):
        return ceil(num)
    return floor(num)


def get_chars_to_rank_up(chars, new_rank, score_for_rank, n, m, sa, s, sb): # pylint: disable=invalid-name, too-many-arguments
    """Determine the number of characters needed to achieve a given rank."""
    target_score = None
    target_rank = new_rank - 1
    # There are gaps in rankings for ties. Find the next highest rank.
    while True:
        assert target_rank > 0
        if target_rank in score_for_rank:
            break
        else:
            target_rank -= 1

    target_score = score_for_rank[target_rank]
    assert chars > sa
    if chars == s:
        # This is the top score for the language. Improving it will affect Sb.
        to_rank_up = floor_with_tolerance(1000 * sa * m / (target_score * (n + m) - 1000 * n))
    else:
        to_rank_up = floor_with_tolerance(1000 * sb / target_score)

    # Check to make sure the results make sense.
    next_sb = (n / (n + m)) * min(s, to_rank_up) + (m / (n + m)) * min(sa, to_rank_up)
    next_score = 1000 * next_sb / to_rank_up
    assert next_score > target_score or isclose(next_score, target_score)
    return to_rank_up


def write_hole_worksheet(cursor, hole, worksheet, formats): # pylint: disable=too-many-locals
    """Write a worksheet for a specific hole."""
    query = '''
        SELECT user,
               lang,
               N,
               M,
               S,
               Sa,
               Sb,
               strokes,
               new_score
          FROM scores
         WHERE hole = ?
      ORDER BY new_score DESC, submitted'''
    results = list(cursor.execute(query, [hole]))
    old_results = {(entry.user, entry.lang): entry for entry in get_leaderboard(cursor, hole)}

    headers = ['User', 'Language', 'Chars', 'New Score', 'New Rank', 'Old Score', 'Old Rank',
               'Δ Score', 'Δ Rank', 'To Rank Up', 'Lang. Sb', 'Lang. S', 'All S', 'Lang. N',
               'Lang. M']

    worksheet.freeze_panes(1, 0)
    # set column width
    worksheet.set_column(get_column_range_reference(headers, 'User'), 22)
    worksheet.set_column(get_column_range_reference(headers, 'To Rank Up'), 10)

    for index, item in enumerate(headers):
        worksheet.write(0, index, item)

    last_rank = None
    score_for_rank = {}

    for index, item in enumerate(results):
        user = item[0]
        language = item[1]
        new_rank = index + 1
        n = item[2]  # pylint: disable=invalid-name
        m = item[3]  # pylint: disable=invalid-name
        s = item[4]  # pylint: disable=invalid-name
        sa = item[5] # pylint: disable=invalid-name
        sb = item[6] # pylint: disable=invalid-name
        chars = item[7]
        new_score = item[8]
        old_entry = old_results[user, language]

        if last_rank and isclose(new_score, score_for_rank[last_rank]):
            new_rank = last_rank

        last_rank = new_rank
        score_for_rank[new_rank] = new_score

        to_rank_up = None
        if new_rank > 1:
            to_rank_up = get_chars_to_rank_up(
                chars, new_rank, score_for_rank, n, m, sa, s, sb)

        data = [user, language, chars, 0, new_rank, old_entry.points, old_entry.rank, 0, 0,
                to_rank_up, sb, s, sa, n, m]

        for column_index, column in enumerate(data):
            worksheet.write(index + 1, column_index, column, formats.get(headers[column_index]))

        def get_reference(name):
            return get_column_reference(headers, name) + str(index + 2)
        def set_column_value(name, value):
            worksheet.write(index + 1, headers.index(name), value, formats[name])

        set_column_value('New Score', f'=1000*{get_reference("Lang. Sb")}/{get_reference("Chars")}')
        set_column_value('Δ Score', f'={get_reference("New Score")}-{get_reference("Old Score")}')
        set_column_value('Δ Rank', f'={get_reference("New Rank")}-{get_reference("Old Rank")}')

        N = get_reference('Lang. N')     # pylint: disable=invalid-name
        M = get_reference('Lang. M')     # pylint: disable=invalid-name
        S = get_reference('Lang. S') # pylint: disable=invalid-name
        Sa = get_reference('All S')    # pylint: disable=invalid-name
        sb_formula = f'=({N} / ({N} + {M})) * {S} + ({M} / ({N} + {M})) * {Sa}'
        set_column_value('Lang. Sb', sb_formula)


def make_spreadsheet(cursor, workbook, holes):
    """Write a spreadsheet showing how the Bayesian scoring method will affect things."""
    number_format1 = workbook.add_format({'num_format': '0.000'})
    number_format2 = workbook.add_format({'num_format': '0.00'})
    number_format3 = workbook.add_format({'num_format': '0.00;[Red]-0.00;0.00'})
    number_format4 = workbook.add_format({'num_format': '[Red]0;-0;0'})
    formats = {'Lang. M': number_format1,
               'Lang. Sb': number_format2,
               'New Score': number_format2,
               'Δ Score': number_format3,
               'Δ Rank': number_format4,
               'Strokes/Hole': number_format1}

    write_all_holes_worksheet(cursor, workbook.add_worksheet('all-holes'), formats)

    for hole in sorted(holes):
        worksheet = workbook.add_worksheet(hole[:31])
        write_hole_worksheet(cursor, hole, worksheet, formats)


def _main():
    parser = ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--local', '-l', action='store_true', help='Use local files instead of '
                       'downloading new ones. Saves about 30 seconds.')
    group.add_argument('--remote', '-r', action='store_true', help='Download new files instead of'
                       'using local files. Must be used at least once before using --local.')
    args = parser.parse_args()
    try:
        os.mkdir(os.path.join(DIR, 'scores'))
    except FileExistsError:
        pass
    time1 = time()
    if args.local:
        print("Using local cache.")
    else:
        print("Downloading new files. Please wait.")
    all_solutions = get_all_solutions(args.local)
    print(f'Loaded data in {time() - time1:.1f} seconds.')
    holes = {solution.hole for solution in all_solutions}
    user_count = len({solution.user for solution in all_solutions})
    print(f'Got {len(holes)} holes.')
    print(f'Got {user_count} users.')
    print(f'Got {len(all_solutions)} solutions.')
    db_filename = os.path.join(DIR, 'scores.db')
    try:
        os.unlink(db_filename)
    except OSError:
        pass
    connection = sqlite3.connect(db_filename)
    cursor = connection.cursor()
    make_database(cursor, all_solutions)
    filename = os.path.join(DIR, 'bayesian.xlsx')
    workbook = xlsxwriter.Workbook(filename)
    make_spreadsheet(cursor, workbook, holes)
    workbook.close()
    print(f'Wrote file: {filename}')
    connection.commit()
    connection.close()
    print(f'Wrote file: {db_filename}')


if __name__ == '__main__':
    _main()
