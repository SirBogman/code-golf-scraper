#!/usr/bin/env python3
"""Download all of the scores from code-golf.io and create a spreadsheet showing how the proposed
Bayesian scoring method will affect things."""

import os
import re
import sqlite3
from argparse import ArgumentParser
from collections import defaultdict
from dataclasses import dataclass
from math import ceil, floor, isclose

import requests
import xlsxwriter

DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass
class UserInfo:
    """Represents a user's overall score."""
    name: str
    score: int
    rank: int
    holes: int


@dataclass
class SolutionInfo:
    """Represents a solution to a hole."""
    rank: int
    user: str
    language: str
    hole: str
    chars: int
    score: int
    sort_index: int


SHORT_REGEX = re.compile(r'<tr><td>(?P<rank>[\d,]+)<sup>\w+</sup>')

SOLUTION_REGEX = re.compile(
    r'<tr><td>(?P<rank>[\d,]+)<sup>\w+</sup>'
    r'<td><img src="[^"]+"><a href="/users/(?P<user>[\-\w]+)">(?P=user)</a>'
    r'<td class=(?P<language>\w+)>(?P<chars>[\d,]+)'
    r'<td>\((?P<score>[\d,]+) points?\)'
    r'<td><time datetime=(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})Z>[\s\w]+</time>')

TOTAL_SCORES_REGEX = re.compile(
    r'<tr><td>(?P<rank>[\d,]+)<sup>\w+</sup>'
    r'<td><img src="[^"]+"><a href="/users/(?P<user>[\-\w]+)">(?P=user)</a>'
    r'<td>(?P<score>[\d,]+)'
    r'<td>\((?P<holes>[\d,]+) holes?\)'
    r'<td><time datetime=(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})Z>[\s\w]+</time>')


def get_from_web(hole):
    """Get html for a hole from the web."""
    return requests.get(f'https://code-golf.io/scores/{hole}/all-langs').text


def get_file_path(hole):
    """Get a local path for caching an html file."""
    return os.path.join(DIR, 'scores', hole + '.html')


def get_from_file(hole):
    """Get html for a hole from a file."""
    with open(get_file_path(hole), 'r', encoding='utf-8') as file:
        return file.read()


def _parse_solution(hole, match, count):
    return SolutionInfo(
        rank=int(match.group('rank').replace(',', '')),
        user=match.group('user'),
        language=match.group('language'),
        hole=hole,
        chars=int(match.group('chars').replace(',', '')),
        score=int(match.group('score').replace(',', '')),
        sort_index=count + 1)


def process_hole_list(html):
    """Parse the list of all holes."""
    match = re.search(r'<select id=hole>(.*?)</select>', html.replace('\n', ''))
    if not match:
        print('Failed to detect holes')
        exit(1)
    return set(re.findall('value=([^>]+)>', match.group(0))) - {'all-holes'}


def get_holes_and_users(use_local_cache):
    """Get the hole names and each user's overall score and rank."""
    if use_local_cache:
        html = get_from_file('all-holes')
    else:
        html = get_from_web('all-holes')
        with open(get_file_path('all-holes'), 'w', encoding='utf-8') as file:
            file.write(html)
    holes = process_hole_list(html)
    user_infos = {}
    for match in TOTAL_SCORES_REGEX.finditer(html):
        user = match.group('user')
        user_infos[user] = UserInfo(
            name=user,
            score=int(match.group('score').replace(',', '')),
            rank=int(match.group('rank').replace(',', '')),
            holes=int(match.group('holes').replace(',', '')))

    expected_user_count = len(SHORT_REGEX.findall(html))
    user_count = len(user_infos)
    if expected_user_count != user_count:
        print(f'Expected {expected_user_count} users, but found {user_count}. Check regex.')
        exit(1)
    if not user_count:
        print(f'No users found. Check regex.')
        exit(1)
    return holes, user_infos


def get_all_solutions(use_local_cache, holes):
    """Get the user, language, character count, score, rank, and sort index for each solution."""
    all_solutions = defaultdict(list)
    for hole in sorted(holes):
        if use_local_cache:
            html = get_from_file(hole)
        else:
            html = get_from_web(hole)
            with open(get_file_path(hole), 'w', encoding='utf-8') as file:
                file.write(html)

        last_rank = 0
        next_rank = 1
        solutions = []
        for match in SOLUTION_REGEX.finditer(html):
            info = _parse_solution(hole, match, len(solutions))
            solutions.append(info)
            # Make sure we're not missing any scores.
            if info.rank != last_rank and info.rank != next_rank:
                print(f'Internal error at rank={info.rank} last_rank={last_rank} in {hole}.')
                exit(1)
            last_rank = info.rank
            next_rank += 1

        all_solutions[hole] = solutions
        expected_hole_solution_count = len(SHORT_REGEX.findall(html))
        hole_solution_count = len(solutions)
        if expected_hole_solution_count != hole_solution_count:
            print(f'Internal error for {hole}. Expected {expected_hole_solution_count} matches, '
                  f'but found {hole_solution_count}. Check regex.')
            exit(1)
        if not hole_solution_count:
            print(f'No solutions found for hole {hole}. Check regex.')
            exit(1)
    return all_solutions


def make_database(cursor, all_scores):
    """Put all of the solutions into a database for easy querying."""
    cursor.execute('''create table solutions
        (hole text, user text, language text, size int, score int, rank int, sort_index int,
         primary key (hole, user, language))''')
    cursor.execute('''create view m_values as
        select
            language,
            2.0 * NLang / Nmax + 1 as M
          from (
            select language, count(*) as NLang from solutions group by language
          )
          cross join (
            select count(*) as Nmax from solutions group by language order by count(*) desc limit 1
          )''')
    cursor.execute('''create view bayesian as
        select
            t1.language,
            t1.hole,
            N,
            M,
            S,
            Sa,
            (N / (N + M)) * S + (M / (N + M)) * Sa as Sb
          from (
            select language, hole, count(*) as N, min(size) as S
            from solutions
            group by language, hole
          ) as t1
          inner join (
            select hole, min(size) as Sa from solutions group by hole
          ) as t2
            on t1.hole = t2.hole
          inner join m_values
          on t1.language = m_values.language''')
    cursor.execute('''create view scores as
        select
            user,
            hole,
            language,
            N,
            M,
            S,
            Sa,
            Sb,
            size,
            1000 * Sb / size as new_score,
            score as old_score,
            rank as old_rank,
            sort_index as old_sort_index
          from solutions
          inner join bayesian using(language, hole)''')
    cursor.execute('''create view total_scores as
        select
            user,
            sum(new_score) as total_score,
            sum(old_score) as rough_old_total_score,
            count(*) as holes,
            sum(size) as strokes
          from (
            select
                user,
                hole,
                min(size) as size,
                max(new_score) as new_score,
                max(old_score) as old_score
              from scores
              group by user, hole
          )
          group by user''')
    data = [(s.hole, s.user, s.language, s.chars, s.score, s.rank, s.sort_index)
            for hole_scores in all_scores.values()
            for s in hole_scores]
    cursor.executemany('INSERT INTO solutions VALUES (?,?,?,?,?,?,?)', data)


def get_column_reference(headers, name):
    """Make an Excel-style column reference."""
    return chr(ord('A') + headers.index(name))


def get_column_range_reference(headers, name):
    """Make an Excel-style column range reference for a single column."""
    reference = get_column_reference(headers, name)
    return f'{reference}:{reference}'


def write_all_holes_worksheet(cursor, users, worksheet, formats):
    """Write a worksheet for all-holes."""
    worksheet.freeze_panes(1, 0)
    headers = ['User', 'New Score', 'New Rank', 'Old Score', 'Old Rank', 'Δ Score', 'Δ Rank',
               'Strokes', 'Holes', 'Strokes/Hole']
    # set column width
    worksheet.set_column(get_column_range_reference(headers, 'User'), 22)
    worksheet.set_column(get_column_range_reference(headers, 'Strokes/Hole'), 11)
    for index, item in enumerate(headers):
        worksheet.write(0, index, item)

    results = list(cursor.execute(
        'select user, total_score, holes, strokes from total_scores order by total_score desc'))
    for index, item in enumerate(results):
        user = users[item[0]]
        assert user.holes == item[2]
        data = [user.name, item[1], index + 1, user.score, user.rank, 0, 0, item[3], user.holes]
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


def get_chars_to_rank_up(chars, new_rank, score_for_rank, n, m, sa, s, sb):
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


def write_hole_worksheet(cursor, hole, worksheet, formats):
    """Write a worksheet for a specific hole."""
    query = '''select user,
            language,
            N,
            M,
            S,
            Sa,
            Sb,
            size,
            new_score,
            old_score,
            old_rank from scores
            where hole = ?
            order by new_score desc, old_sort_index'''
    results = list(cursor.execute(query, [hole]))
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
        old_score = item[9]
        old_rank = item[10]

        if last_rank and isclose(new_score, score_for_rank[last_rank]):
            new_rank = last_rank

        last_rank = new_rank
        score_for_rank[new_rank] = new_score

        to_rank_up = None
        if new_rank > 1:
            to_rank_up = get_chars_to_rank_up(
                chars, new_rank, score_for_rank, n, m, sa, s, sb)

        data = [user, language, chars, 0, new_rank, old_score, old_rank, 0, 0,
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


def make_spreadsheet(cursor, workbook, holes, users):
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

    write_all_holes_worksheet(cursor, users, workbook.add_worksheet('all-holes'), formats)

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
    if args.local:
        print("Using local cache.")
    else:
        print("Downloading new files. Please wait.")
    holes, users = get_holes_and_users(args.local)
    print(f'Got {len(holes)} holes.')
    print(f'Got total scores for {len(users):,} users.')
    all_solutions = get_all_solutions(args.local, holes)
    print(f'Got {sum(len(s) for s in all_solutions.values()):,} solutions.')
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
    make_spreadsheet(cursor, workbook, holes, users)
    workbook.close()
    print(f'Wrote file: {filename}')
    connection.commit()
    connection.close()
    print(f'Wrote file: {db_filename}')


if __name__ == '__main__':
    _main()
