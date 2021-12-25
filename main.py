import json
import logging
import time
from collections import defaultdict
from typing import List, Dict, Set, Optional

import click
import requests

from config import GITHUB_API_TOKEN


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    force=True,
)


@click.group()
def cli():
    pass


headers = {
    'Authorization': f'token {GITHUB_API_TOKEN}',
    'Accept': 'application/vnd.github.v3+json',
}


def search_repositories(min_stars: int, max_stars: Optional[int] = None) -> List[Dict]:
    sleep_time = 0.5
    repo_search_url = 'https://api.github.com/search/repositories'

    params = {
        'q': f'stars:>={min_stars}',
        'sort': 'stars',
        'per_page': 100,  # max number allowed
        'page': 1,
    }

    if min_stars and max_stars:
        params['q'] = f' stars:{min_stars}..{max_stars}'

    logging.info(f'Searching repositories with a stars range of [{min_stars},{max_stars}]...')

    response = requests.get(repo_search_url, headers=headers, params=params)
    total_count = response.json()['total_count']
    if total_count > 1000:
        raise Exception("GitHub API allows to query maximum of 1000 results per request.")
    pages_num = (total_count // params['per_page']) + 1
    logging.info(f'Found {total_count} repositories. Start querying {pages_num} pages...')

    should_stop = False
    items = []

    while not should_stop:
        response = requests.get(repo_search_url, headers=headers, params=params)
        if response.status_code == 200:
            items.extend(response.json()['items'])
            total_count = response.json()['total_count']
            should_stop = params['per_page'] * params['page'] >= total_count
            logging.info(f'Finished page {params["page"]} out of {pages_num}.')
            params['page'] += 1
        else:
            logging.error(f'Response code is {response.status_code}. Body:\n{response.json()}')
        time.sleep(sleep_time)

    logging.info(f'Collected {len(items)} repositories.')
    return items


def build_graphql_query(login: str, cursor: str = "") -> Dict[str, str]:
    if cursor:
        cursor = f",after: \"{cursor}\""
    return {
        "query":
            "{organization(login: \"%s\") {projectsNext(first: 100 %s) {nodes {id, title, url}, pageInfo {endCursor}}}}"
            % (login, cursor)
    }


def query_organization_projects(org: str) -> List[Dict]:
    graphql_url = f'https://api.github.com/graphql'
    should_stop = False
    cursor = ''
    filtered_projects = []

    while not should_stop:
        query = build_graphql_query(org, cursor)
        response = requests.post(graphql_url, headers=headers, json=query)
        cursor = response.json()['data']['organization']['projectsNext']['pageInfo']['endCursor']
        if not cursor:
            should_stop = True

        projects = response.json()['data']['organization']['projectsNext']['nodes']
        filtered_projects.extend([p for p in projects if p])
    return filtered_projects


def split_by_owner_type(repos: List[Dict]) -> Dict[str, Set[str]]:
    owner_types = defaultdict(set)
    for repo in repos:
        owner_type = str(repo['owner']['type']).lower()
        login = str(repo['owner']['login'])
        owner_types[owner_type].add(login)
    return owner_types


def query_new_projects_by_organization(organizations: List[str]) -> Dict[str, List]:
    total_organizations = len(organizations)
    sleep_time = 0.5
    results = {}

    logging.info(f'Extracting projects from {total_organizations} organizations...')
    for index, org in enumerate(organizations):
        try:
            projects = query_organization_projects(org)
            if projects:
                results[org] = projects
            logging.info(f'Finished organization {index + 1} out of {total_organizations}.')
        except Exception as error:
            logging.error(f'Cannot retrieve projects for {org}. Error:\n{error}\nSkipping...')
        time.sleep(sleep_time)
    return results


def build_markdown(data: Dict[str, List]) -> str:
    output = '# List of organizations and their public new GitHub Projects\n\n'
    for organization, projects in data.items():
        output += f'## {organization}\n\n'
        output += '| Title | URL |\n' \
                  '| ------------- |: -------------: |\n'
        for project in projects:
            title = project['title']
            url = project['url']
            output += f'| {title} | {url} |\n'

        output += '\n'

    return output


def save(data, name):
    with open(name, 'w') as f:
        json.dump(data, f)


def load(name):
    with open(name) as f:
        return json.load(f)


@cli.command('collect-repositories')
@click.option('--min_stars', type=int, required=True, help='Minimum number of GitHub stars')
@click.option('--max_stars', type=int, help='Maximum number of GitHub stars')
@click.option('-o', '--output', type=click.Path(), required=True,
              help='Path where to save collected repositories in JSON.')
def collect_repositories(min_stars: int,
                         max_stars: Optional[int],
                         output: str) -> None:
    """Collect GitHub repositories with specified limit of stars."""
    repositories = search_repositories(min_stars=min_stars, max_stars=max_stars)
    save(repositories, output)


@cli.command('collect-projects')
@click.option('-i', '--input', 'repositories_path', type=click.Path(exists=True), required=True,
              help='Path to collected repositories in JSON.')
@click.option('-o', '--output', 'projects_path', type=click.Path(), required=True,
              help='Path where to save collected new Projects in JSON.')
def collect_projects(repositories_path: str, projects_path: str) -> None:
    """Query public new Projects based on collected repositories."""
    repositories = load(repositories_path)
    repositories_by_owner_types = split_by_owner_type(repositories)
    organizations = repositories_by_owner_types.get('organization', [])
    organizations_new_projects = query_new_projects_by_organization(organizations)
    save(organizations_new_projects, projects_path)


@cli.command('generate-markdown')
@click.option('-i', '--input', 'projects_path', type=click.Path(exists=True), required=True,
              help='Path to collected projects in JSON.')
@click.option('-o', '--output', 'markdown_path', type=click.Path(), required=True,
              help='Path where to save generated markdown file with projects.')
def generate_markdown(projects_path: str, markdown_path: str) -> None:
    """Generate Markdown file from collected projects."""
    organizations_to_new_projects = load(projects_path)
    markdown = build_markdown(organizations_to_new_projects)
    with open(markdown_path, 'w') as f:
        f.write(markdown)


if __name__ == '__main__':
    cli()
