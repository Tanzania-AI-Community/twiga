# Development Workflow

This project follows a slightly modified GitFlow workflow to ensure stability and manage releases effctively.

## Branch Structure

- `main`: Represents the current production state.
- `development`: The main integration branch where features are merged for testing.
- `feature/*`: Feature branches.
- `hotfix/*`: Hotfix branches.
- `release/v*.*.*`: Release branches.
- `chore/*`: Maintenance branches.

## Workflow Guidelines

1. **Feature Development**

   - Create a new feature branch from `development`:

     ```shell
     git checkout development
     git pull origin development
     git checkout -b feature/your-feature-name
     ```

     - Develop your feature and keep your commits clear and granular.
     - When ready, open a pull request to merge your branch into `development`.

2. **Code Review and Integration**

   - All pull requests must be reviewed by at least one other developer.
   - CI checks must pass before merging.
   - Once approved, merge the feature branch into `development`.
   - Delete the feature branch after successful merge.

3. **Preparing a Release**

   - Create a release branch from `development`:

     ```shell
     git checkout development
     git pull origin development
     git checkout -b release/v1.x.x
     ```

   - Perform final testing and bug fixes on the release branch.
   - Update version numbers and changelog.
   - (POSSIBLY) Update .all-contributors and have the PR go to the development branch

4. **Production Release**

   - When the release is ready, open a pull request to merge into `main`.
   - After final review and approval, merge into `main`.
   - Tag the release in `main`:

     ```shell
     git checkout main
     git pull origin main
     git tag -a v1.x.x -m "Release v1.x.x"
     git push origin v1.x.x
     ```

   - Merge the release branch back into `development`.

5. **Hotfixes**

   - For critical bugs in production, create a hotfix branch from `main`:

     ```shell
     git checkout main
     git checkout -b hotfix/descriptive-name
     ```

   - Fix the bug and open a pull request to merge into both `main` and `dev`.

6. **Refactoring**

   - For refactoring issues, create a refactor branch from `development`:

   ```shell
   git checkout development
   git checkout -b refactor/descriptive-name
   ```

   - Do the refactor and open a pull request to merge into `development`.

### Merge and Rebase Policy

This project uses a combination of rebasing and merging to maintain a clean and informative history:

1. **Feature Branches:** Use rebase to keep feature branches up-to-date with `development`:

   ```shell
   git checkout feature/your-feature
   git rebase development
   ```

   This creates a linear history for the feature, making it easies to understand and review.

2. **Merging Features:** When a feature is complete, merge it into `development` using a no-fast-forward merge:

   ```shell
   git checkout development
   git merge --no-ff feature/your-feature
   ```

   This preserves the feature branch history in the `development` branch.

3. **Release and Hotfix Branches:** Use merge (not rebase) when integrating `development` into release branches, or when merging releases and hotfixes into `main`and `development`:

   ```shell
   git checkout main
   git merge --no-ff release/v1.x.x
   ```

   This maintains a record of when releases and hotfixes where integrated.

> [!Warning]
>
> Never rebase branches that have been pushed to the remote repository and may be in use by other team members.

### Best Practices

1. **Commit Messages**: Use clear, descriptive commit messages. Follow the [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) specification:

   ```shell
   type(scope): description

   [optional body]

   [optional footer]
   ```

   Types: feat, fix, docs, style, refactor, test, chore

   **Scope** refers to the component or module affected by the change.

   **Description** should be a short, imperative sentence that starts with a verb.

   **Footer** can be used to reference issues by ID, PRs, or other resources.

   Specific examples:

   a) Adding a new feature:

   ```shell
   feat(knowledge-graph): implement new node linking algorithm

   - Update API endpoint /api/v1/link-nodes to use new algorithm

   Closes AIS-123
   ```

   b) Fixing a bug:

   ```
   fix(api): resolve race condition in concurrent augmenting solution request

   - Add mutex lock in LLMService
   - Implement retry mechanism for failed solves
   - Update error handling to provide more detailed feedback

   Fixes AIS-456
   ```

   c) Refactoring existing code:

   ```
   refactor(llm): optimize token usage in query generation

   - Rewrite QueryGenerator to use more efficient prompts
   - Reduce redundant context in follow-up questions
   - Implement caching for frequently used prompt templates

   Performance improvement of ~15% in token usage
   ```

   d) Updating documentation:

   ```
   docs(readme): update API usage examples

   - Add examples for new mathematical concept endpoints
   - Include section on error handling best practices
   ```

   e) Making a breaking change:

   ```
   feat(api)!: revise authentication mechanism for increased security

   - Replace JWT with OAuth2
   - Update all protected endpoints to use new auth flow
   - Implement key rotation and expiry

   BREAKING CHANGE: API now requires OAuth2 token instead of JWT.
   ```

2. **Pull Requests**:

   - Keep PRs small and focused on a single feature or bug fix.
   - Include a description of changes and any necessary context.
   - Link related issues in the PR description.

3. **Code Review**:

   - Review for code quality, performance, and adherence to project standards.
   - Use GitHub's suggestion feature for proposing changes.
   - Approve only when all comments have been addressed.

4. **Versioning**:

   - Follow semantic versioning (MAJOR.MINOR.PATCH).
   - Update the version number in the appropriate files before creating a release.

5. **Testing**:

   - Write and update tests for all new features and bug fixes.
   - Ensure all tests pass before opening a pull request.

6. **Documentation**:
   - Update relevant documentation as part of your changes.
   - Include inline comments for complex logic.

### CI/CD Pipeline

Our CI/CD pipeline automatically runs the following checks:

- Linting (ruff)

- Formatting (black)

- Unit tests (tbd...)

Deployments:

- All pull requests trigger a preview deployment.
- Merges to `development` trigger a deployment to the staging environment after manual approval.
- Merges to `main` trigger a deployment to the production environment after manual approval.
