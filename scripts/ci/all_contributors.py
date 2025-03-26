#!/usr/bin/env python3

import json
import os
import argparse
import requests
from typing import List, Dict, Any

# Constants
GITHUB_API_URL = "https://api.github.com"
CONFIG_FILE = ".all-contributorsrc"
README_START_MARKER = (
    "<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->"
)
README_END_MARKER = "<!-- ALL-CONTRIBUTORS-LIST:END -->"

# Valid contribution types as per all-contributors specification
VALID_CONTRIBUTION_TYPES = [
    "audio",
    "a11y",
    "bug",
    "blog",
    "business",
    "code",
    "content",
    "data",
    "doc",
    "design",
    "example",
    "eventOrganizing",
    "financial",
    "fundingFinding",
    "ideas",
    "infra",
    "maintenance",
    "mentoring",
    "platform",
    "plugin",
    "projectManagement",
    "promotion",
    "question",
    "research",
    "review",
    "security",
    "tool",
    "translation",
    "test",
    "tutorial",
    "talk",
    "userTesting",
    "video",
]

# Emoji mapping for different contribution types
CONTRIBUTION_TYPE_EMOJI = {
    "audio": "🔊",
    "a11y": "♿️",
    "bug": "🐛",
    "blog": "📝",
    "business": "💼",
    "code": "💻",
    "content": "🖋",
    "data": "🔣",
    "doc": "📖",
    "design": "🎨",
    "example": "💡",
    "eventOrganizing": "📋",
    "financial": "💵",
    "fundingFinding": "🔍",
    "ideas": "🤔",
    "infra": "🚇",
    "maintenance": "🚧",
    "mentoring": "🧑‍🏫",
    "platform": "📦",
    "plugin": "🔌",
    "projectManagement": "📆",
    "promotion": "📣",
    "question": "💬",
    "research": "🔬",
    "review": "👀",
    "security": "🛡️",
    "tool": "🔧",
    "translation": "🌍",
    "test": "⚠️",
    "tutorial": "✅",
    "talk": "📢",
    "userTesting": "📓",
    "video": "📹",
}


def load_config() -> Dict[str, Any]:
    """Load the .all-contributorsrc configuration file"""
    if not os.path.exists(CONFIG_FILE):
        return {
            "projectName": "",
            "projectOwner": "",
            "files": ["README.md"],
            "commitType": "docs",
            "commitConvention": "angular",
            "contributorsPerLine": 7,
            "contributors": [],
        }

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(config: Dict[str, Any]) -> None:
    """Save the updated config to .all-contributorsrc"""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_github_user_info(username: str) -> Dict[str, Any]:
    """Fetch user information from GitHub API"""
    response = requests.get(f"{GITHUB_API_URL}/users/{username}")
    if response.status_code == 200:
        user_data = response.json()
        return {
            "login": user_data["login"],
            "name": user_data["name"] or user_data["login"],
            "avatar_url": user_data["avatar_url"],
            "profile": user_data["html_url"],
        }
    else:
        print(
            f"Failed to fetch GitHub user information for {username}. Using placeholder data instead."
        )
        raise Exception(f"Failed to fetch GitHub user information for {username}")


def add_contributor(
    config: Dict[str, Any], github_username: str, contributions: List[str]
) -> Dict[str, Any]:
    """Add a new contributor or update an existing one"""
    # Validate contribution types
    valid_contributions = []
    for contribution in contributions:
        if contribution in VALID_CONTRIBUTION_TYPES:
            valid_contributions.append(contribution)
        else:
            print(
                f"Warning: {contribution} is not a valid contribution type. Skipping."
            )

    if not valid_contributions:
        print(f"No valid contributions specified for {github_username}. Skipping.")
        return config

    # Check if the contributor already exists
    for i, contributor in enumerate(config["contributors"]):
        if contributor["login"].lower() == github_username.lower():
            # Update existing contributor
            unique_contributions = set(
                contributor["contributions"] + valid_contributions
            )
            config["contributors"][i]["contributions"] = sorted(
                list(unique_contributions)
            )
            print(f"Updated contributions for {github_username}")
            return config

    # Add new contributor
    user_info = get_github_user_info(github_username)
    user_info["contributions"] = valid_contributions
    config["contributors"].append(user_info)
    print(f"Added new contributor: {github_username}")

    return config


def generate_contributor_table(config: Dict[str, Any]) -> str:
    """Generate HTML for the contributors table"""
    contributors = config["contributors"]
    contributors_per_line = config.get("contributorsPerLine", 7)

    html = []
    html.append("<!-- prettier-ignore-start -->")
    html.append("<!-- markdownlint-disable -->")
    html.append("<table>")
    html.append("  <tbody>")

    # Generate rows of contributors
    for i in range(0, len(contributors), contributors_per_line):
        row_contributors = contributors[i : i + contributors_per_line]
        html.append("    <tr>")

        for contributor in row_contributors:
            avatar_url = contributor["avatar_url"]
            profile = contributor["profile"]
            name = contributor["name"]
            login = contributor["login"]
            contributions = contributor["contributions"]

            # Calculate cell width
            cell_width = 100 / contributors_per_line

            # Start the table cell
            html.append(f'      <td align="center" valign="top" width="{cell_width}%">')

            # Add avatar with link
            html.append(
                f'<a href="{profile}"><img src="{avatar_url}?s=100" width="100px;" alt="{name}"/>'
            )

            # Add name
            html.append(f"<br /><sub><b>{name}</b></sub></a>")

            # Add contribution icons
            html.append("<br />")
            for contribution in contributions:
                if contribution in CONTRIBUTION_TYPE_EMOJI:
                    emoji = CONTRIBUTION_TYPE_EMOJI[contribution]
                    title = contribution
                    html.append(
                        f'<a href="#{contribution}-{login}" title="{title}">{emoji}</a> '
                    )

            # Close the table cell
            html.append("</td>")

        html.append("    </tr>")

    html.append("  </tbody>")
    html.append("</table>")
    html.append("")
    html.append("<!-- markdownlint-restore -->")
    html.append("<!-- prettier-ignore-end -->")

    return "\n".join(html)


def update_readme(config: Dict[str, Any]) -> None:
    """Update the README.md file with the contributors table"""
    for file_path in config["files"]:
        if not os.path.exists(file_path):
            print(f"Warning: {file_path} does not exist. Skipping.")
            continue

        with open(file_path, "r") as f:
            content = f.read()

        # Find the contributors section
        start_index = content.find(README_START_MARKER)
        end_index = content.find(README_END_MARKER)

        if start_index == -1 or end_index == -1:
            print(
                f"Warning: Contributors section markers not found in {file_path}. Adding to the end."
            )
            content += f"\n\n{README_START_MARKER}\n{generate_contributor_table(config)}\n{README_END_MARKER}\n"
        else:
            # Replace the existing contributors section
            content = (
                content[: start_index + len(README_START_MARKER)]
                + "\n"
                + generate_contributor_table(config)
                + "\n\n"
                + content[end_index:]
            )

        with open(file_path, "w") as f:
            f.write(content)

        print(f"Updated contributors section in {file_path}")


def main():
    """Main function to parse arguments and execute the script"""
    parser = argparse.ArgumentParser(
        description="Manage contributors in a GitHub repository"
    )

    # Setup subparsers for different commands
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # 'add' command
    add_parser = subparsers.add_parser(
        "add", help="Add a new contributor or update an existing one"
    )
    add_parser.add_argument("username", help="GitHub username of the contributor")
    add_parser.add_argument(
        "contributions",
        nargs="+",
        help=f"Types of contributions. Valid types: {', '.join(VALID_CONTRIBUTION_TYPES)}",
    )

    # 'init' command
    init_parser = subparsers.add_parser(
        "init", help="Initialize the .all-contributorsrc file"
    )
    init_parser.add_argument(
        "--project-name", required=True, help="Name of the project"
    )
    init_parser.add_argument(
        "--project-owner",
        required=True,
        help="GitHub username or organization that owns the project",
    )
    init_parser.add_argument(
        "--contributors-per-line",
        type=int,
        default=7,
        help="Number of contributors per line in the table",
    )

    # # 'update' command
    # update_parser = subparsers.add_parser(
    #     "update", help="Update the README.md with the current contributors"
    # )

    args = parser.parse_args()

    if args.command == "init":
        # Initialize the .all-contributorsrc file
        config = {
            "projectName": args.project_name,
            "projectOwner": args.project_owner,
            "files": ["README.md"],
            "commitType": "docs",
            "commitConvention": "angular",
            "contributorsPerLine": args.contributors_per_line,
            "contributors": [],
        }
        save_config(config)
        print(
            f"Initialized {CONFIG_FILE} with project name: {args.project_name}, owner: {args.project_owner}"
        )

    elif args.command == "add":
        # Add or update a contributor
        config = load_config()
        config = add_contributor(config, args.username, args.contributions)
        save_config(config)
        update_readme(config)
        print(
            f"Added/updated contributor {args.username} with contributions: {', '.join(args.contributions)}"
        )

    elif args.command == "update":
        # Update README.md with current contributors
        config = load_config()
        update_readme(config)
        print("Updated README.md with current contributors")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
