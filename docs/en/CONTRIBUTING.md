# Contributing to Twiga 🦒

We welcome contributions of any size and skill level. As an open source project, we believe in giving back to our contributors and are happy to help with guidance on pull requests (PRs), technical writing, and turning any feature idea into a reality.

> [!Tip]
>
> **For new contributors 🚼:** Take a look at [first contributions](https://github.com/firstcontributions/first-contributions) for helpful information on contributing. You can of course ask questions in our [Discord](https://discord.gg/bCe2HfZY2C).

By contributing you agree to our [**Code of Conduct**](https://github.com/Tanzania-AI-Community/twiga/blob/main/.github/CODE_OF_CONDUCT.md).

## Merge Policy for Pull Requests

We're using the [Gitflow](https://www.atlassian.com/git/tutorials/comparing-workflows/gitflow-workflow) workflow, meaning we don't do PRs for new features directly to the `main` branch. Any updates to the codebase, whether large or small, are first merged into the `development`. They're then deployed to our development server (basically our staging area) where we can evaluate if there's any breaking changes. After each milestone we submit a PR from `development` to `main`.

> [!Important]
> Submit your PR against the `development` branch, not `main`. We do not accept PRs directly to `main`.

## From Fork to PR with Twiga

> [!Important]
>
> Read our [Git Guidelines](https://github.com/Tanzania-AI-Community/twiga/blob/documentation/docs/en/GIT_GUIDELINES.md) to learn how to develop collaboratively on Twiga like a pro.

To start contributing to Twiga, follow these steps:

1. Create a fork of this repository and clone it to your local machine

> [!Warning]
> Remember to uncheck the "Copy the `main` branch only" so that you get the `development` branch too

2. Checkout the `development` branch: `git checkout development`
3. Create your feature branch from the `development` branch: `git checkout -b your-branch-name`
4. Follow the steps in our [getting started](https://github.com/Tanzania-AI-Community/twiga/blob/documentation/docs/en/GETTING_STARTED.md) guide to get the project up and running locally
5. (Not yet possible) Run the tests to ensure everything is working as expected
6. Commit your changes: `git commit -m "[type]: descriptive commit message"`
7. Push to your remote branch: `git push origin your-branch-name`
8. Submit a pull request to the `development` branch of the original repository

## Code Formatting and Linting

Make sure to follow the established coding style guidelines in this project. We believe consistent formatting of the code makes it easier to understand and debug. Therefore, we enforce good formatting conventions using [_pre-commit_](https://pre-commit.com/) in order to automatically run the Python [_black_](https://github.com/psf/black) and [_ruff_](https://docs.astral.sh/ruff/) formatters on every commit.

Don't worry, you don't need to learn a whole new way of formatting code - it's done for you. Though if you're curious about having these formatters and linters during your development (and not just on commit) we recommend these extensions for VSCode (our preferred editor): [_Black Formatter_](https://marketplace.visualstudio.com/items?itemName=ms-python.black-formatter) and [_Ruff_](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff). When you've completed steps 1-3 in [From Fork to PR with Twiga](#from-fork-to-pr-with-twiga), you can install the dependencies with:

```bash
$ uv sync
$ source .venv/bin/activate
```

> [!Note]
> For **Windows** the second command would be `.venv\Scripts\activate`

Then you can install the _pre-commit_ hooks with:

```bash
$ pre-commit install

# output
> pre-commit installed at .git/hooks/pre-commit
```

### An Example of _pre-commit_ in Action

> [!Note]
> We shamelessly took this example from [gpt-engineer](https://github.com/gpt-engineer-org/gpt-engineer/tree/main). Thanks!

As an introduction of the actual workflow, here is an example of the process you will encounter when you make a commit:

Let's add a file we have modified with some errors, see how the pre-commit hooks run `black` and fails.
`black` is set to automatically fix the issues it finds:

```bash
$ git add random_code_file.py
$ git commit -m "commit message"
black....................................................................Failed
- hook id: black
- files were modified by this hook

reformatted random_code_file.py

All done! ✨ 🍰 ✨
1 file reformatted.
```

You can see that `random_code_file.py` is both staged and not staged for commit. This is because `black` has formatted it and now it is different from the version you have in your working directory. To fix this you can simply run `git add random_code_file.py` again and now you can commit your changes.

```bash
$ git status
On branch pre-commit-setup
Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
    modified:   random_code_file.py

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
    modified:   random_code_file.py
```

Now let's add the file again to include the latest commits and see how `ruff` fails.

```bash
$ git add random_code_file.py
$ git commit -m "commit message"
black....................................................................Passed
ruff.....................................................................Failed
- hook id: ruff
- exit code: 1
- files were modified by this hook

Found 2 errors (2 fixed, 0 remaining).
```

Same as before, you can see that `random_code_file.py` is both staged and not staged for commit. This is because `ruff` has formatted it and now it is different from the version you have in your working directory. To fix this you can simply run `git add random_code_file.py` again and now you can commit your changes.

```bash
$ git add random_code_file.py
$ git commit -m "commit message"
black....................................................................Passed
ruff.....................................................................Passed
fix end of files.........................................................Passed
[pre-commit-setup f00c0ce] testing
 1 file changed, 1 insertion(+), 1 deletion(-)
```

Now your file has been committed and you can push your changes.

At the beginning this might seem like a tedious process (having to add the file again after `black` and `ruff` have modified it) but it is actually very useful. It allows you to see what changes `black` and `ruff` have made to your files and make sure that they are correct before you commit them.

> [!Note]
> When pre-commit fails in the build pipeline when submitting a PR you need to run `pre-commit run --all-files` to have it force format all files, not just the ones you edited since the previous commit.

Sometimes `pre-commit` will seemingly run successfully, as follows:

```bash
black................................................(no files to check)Skipped
ruff.................................................(no files to check)Skipped
check toml...........................................(no files to check)Skipped
check yaml...........................................(no files to check)Skipped
detect private key...................................(no files to check)Skipped
fix end of files.....................................(no files to check)Skipped
trim trailing whitespace.............................(no files to check)Skipped
```

However, you may see `pre-commit` fail in the build pipeline upon submitting a PR. The solution to this is to run `pre-commit run --all-files` to force

## Licensing

By contributing to Twiga, you agree that your contributions will be licensed under the [License](https://github.com/Tanzania-AI-Community/twiga/blob/main/LICENSE) of the project.

Thank you for your interest in contributing to Twiga! We look forward to your contributions.
