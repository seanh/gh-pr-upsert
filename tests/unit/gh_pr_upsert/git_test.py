from subprocess import CalledProcessError
from unittest.mock import call
from unittest.mock import sentinel as sentinel_

import pytest

from gh_pr_upsert.git import (
    Commit,
    GitHubRepo,
    PullRequest,
    User,
    branch_exists,
    configured_user,
    current_branch,
    diff,
    log,
    push,
)


class TestCommit:
    def test_get(self, run):
        run.side_effect = [
            sentinel_.full_sha,
            sentinel_.author_name,
            sentinel_.author_email,
            sentinel_.committer_name,
            sentinel_.committer_email,
        ]

        commit = Commit.get(sentinel_.sha)

        assert run.call_args_list == [
            call(["git", "show", "--no-patch", "--format=%H", sentinel_.sha]),
            call(["git", "show", "--no-patch", "--format=%an", sentinel_.sha]),
            call(["git", "show", "--no-patch", "--format=%ae", sentinel_.sha]),
            call(["git", "show", "--no-patch", "--format=%cn", sentinel_.sha]),
            call(["git", "show", "--no-patch", "--format=%ce", sentinel_.sha]),
        ]
        assert commit == Commit(
            sha=sentinel_.full_sha,
            author=User(name=sentinel_.author_name, email=sentinel_.author_email),
            committer=User(
                name=sentinel_.committer_name, email=sentinel_.committer_email
            ),
        )


class TestGitHubRepo:
    def test_get(self, run):
        # The JSON returned by `gh repo view`.
        json = {
            "name": sentinel_.repo_name,
            "nameWithOwner": sentinel_.repo_name_with_owner,
            "url": sentinel_.repo_url,
            "owner": {"login": sentinel_.owner_login},
            "defaultBranchRef": {"name": sentinel_.default_branch_name},
        }
        run.side_effect = [sentinel_.remote_url, json]

        repo = GitHubRepo.get(sentinel_.remote)

        assert run.call_args_list == [
            call(["git", "remote", "get-url", sentinel_.remote]),
            call(
                [
                    "gh",
                    "repo",
                    "view",
                    "--json",
                    "owner,name,nameWithOwner,defaultBranchRef,url",
                    sentinel_.remote_url,
                ],
                json=True,
            ),
        ]
        assert repo == GitHubRepo(
            remote=sentinel_.remote,
            owner=sentinel_.owner_login,
            name=sentinel_.repo_name,
            name_with_owner=sentinel_.repo_name_with_owner,
            default_branch=sentinel_.default_branch_name,
            url=sentinel_.repo_url,
            json=json,
        )


class TestPullRequest:
    def test_from_json(self, json):
        pull_request = PullRequest.from_json(
            sentinel_.base_repo, sentinel_.head_repo, sentinel_.head_branch, json
        )

        assert pull_request == PullRequest(
            base_repo=sentinel_.base_repo,
            head_repo=sentinel_.head_repo,
            head_branch=sentinel_.head_branch,
            number=sentinel_.number,
            html_url=sentinel_.html_url,
            json=json,
        )

    def test_create(self, base_repo, head_repo, run, json):
        run.return_value = json

        pull_request = PullRequest.create(
            base_repo,
            sentinel_.base_branch,
            head_repo,
            sentinel_.head_branch,
            sentinel_.title,
            sentinel_.body,
        )

        run.assert_called_once_with(
            [
                "gh",
                "api",
                "--header",
                "X-GitHub-Api-Version:2022-11-28",
                "--method",
                "POST",
                f"/repos/{base_repo.owner}/{base_repo.name}/pulls",
                "-f",
                f"base={sentinel_.base_branch}",
                "-f",
                f"head={head_repo.owner}:{sentinel_.head_branch}",
                "-f",
                f"title={sentinel_.title}",
                "-f",
                f"body={sentinel_.body}",
            ],
            json=True,
        )
        assert pull_request == PullRequest(
            base_repo=base_repo,
            head_repo=head_repo,
            head_branch=sentinel_.head_branch,
            number=sentinel_.number,
            html_url=sentinel_.html_url,
            json=json,
        )

    def test_get(self, base_repo, head_repo, run, json):
        run.return_value = [json]

        pull_request = PullRequest.get(
            base_repo, sentinel_.base_branch, head_repo, sentinel_.head_branch
        )

        run.assert_called_once_with(
            [
                "gh",
                "api",
                "--header",
                "X-GitHub-Api-Version:2022-11-28",
                "--paginate",
                "--method",
                "GET",
                f"/repos/{base_repo.owner}/{base_repo.name}/pulls",
                "-f",
                f"base={sentinel_.base_branch}",
                "-f",
                f"head={head_repo.owner}:{sentinel_.head_branch}",
                "-f",
                "state=open",
            ],
            json=True,
        )
        assert pull_request == PullRequest(
            base_repo=base_repo,
            head_repo=head_repo,
            head_branch=sentinel_.head_branch,
            number=sentinel_.number,
            html_url=sentinel_.html_url,
            json=json,
        )

    def test_get_returns_None_if_there_are_no_matching_prs(
        self, base_repo, head_repo, run
    ):
        run.return_value = None

        assert not PullRequest.get(
            base_repo, sentinel_.base_branch, head_repo, sentinel_.head_branch
        )

    def test_get_raises_if_there_are_multiple_matching_prs(
        self, base_repo, head_repo, pull_request_factory, run
    ):
        # Make the GitHub API return two PRs for the same base repo, head repo
        # and head branch. This should never happen in production: there can't
        # be two open PRs for the same base and head branch, so get() raises
        # AssertionError.
        run.return_value = [
            {"number": pr.number, "html_url": pr.html_url}
            for pr in pull_request_factory.create_batch(
                2,
                base_repo=base_repo,
                head_repo=head_repo,
                head_branch=sentinel_.head_branch,
            )
        ]

        with pytest.raises(AssertionError):
            PullRequest.get(
                base_repo, sentinel_.base_branch, head_repo, sentinel_.head_branch
            )

    def test_close(self, pull_request, run):
        pull_request.close(sentinel_.comment)

        run.assert_called_once_with(
            [
                "gh",
                "pr",
                "close",
                "--repo",
                pull_request.base_repo.name_with_owner,
                "--delete-branch",
                "--comment",
                sentinel_.comment,
                str(pull_request.number),
            ]
        )

    @pytest.fixture
    def json(self):
        """Return a JSON representation of a pull request as from the GitHub API."""
        return {"number": sentinel_.number, "html_url": sentinel_.html_url}


class TestBranchExists:
    def test_it_returns_True_if_the_branch_exists(self, run):
        exists = branch_exists("origin", "my-branch")

        run.assert_called_once_with(
            ["git", "show-ref", "refs/remotes/origin/my-branch"]
        )
        assert exists

    def test_it_returns_False_if_the_branch_doesnt_exist(self, run):
        run.side_effect = CalledProcessError(returncode=1, cmd=sentinel_.cmd)

        assert not branch_exists("origin", "my-branch")

    def test_it_raises_if_it_gets_an_unexpected_exit_code_from_git(self, run):
        run.side_effect = CalledProcessError(returncode=2, cmd=sentinel_.cmd)

        with pytest.raises(CalledProcessError) as exc_info:
            branch_exists("origin", "my-branch")

        assert exc_info.value == run.side_effect


class TestConfiguredUser:
    def test_it(self, user, run):
        run.side_effect = [user.name, user.email]

        assert configured_user() == user
        assert run.call_args_list == [
            call(["git", "config", "--get", "user.name"]),
            call(["git", "config", "--get", "user.email"]),
        ]


class TestCurrentBranch:
    def test_it(self, run):
        branch = current_branch()

        run.assert_called_once_with(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"]
        )
        assert branch == run.return_value


class TestDiff:
    def test_it(self, run):
        returned = diff((sentinel_.branch_1, sentinel_.branch_2))

        run.assert_called_once_with(
            ["git", "diff", sentinel_.branch_1, sentinel_.branch_2]
        )
        assert returned == run.return_value


class TestLog:
    def test_it(self, commit_factory, run, get):
        get.side_effect = commits = commit_factory.create_batch(2)
        run.return_value = "\n".join((commit.sha for commit in commits))

        returned = log((sentinel_.branch_1, sentinel_.branch_2))

        run.assert_called_once_with(
            [
                "git",
                "log",
                "--ignore-missing",
                sentinel_.branch_1,
                sentinel_.branch_2,
                "--format=%H",
            ]
        )
        assert get.call_args_list == [call(commits[0].sha), call(commits[1].sha)]
        assert returned == commits

    @pytest.fixture(autouse=True)
    def get(self, mocker):
        return mocker.patch("gh_pr_upsert.git.Commit.get", autospec=True)


class TestPush:
    def test_it(self, run):
        push(sentinel_.remote, sentinel_.local_branch, sentinel_.remote_branch)

        run.assert_called_once_with(
            [
                "git",
                "push",
                "--force-with-lease",
                sentinel_.remote,
                f"{sentinel_.local_branch}:{sentinel_.remote_branch}",
            ]
        )


@pytest.fixture(autouse=True)
def clear_caches():
    yield

    branch_exists.cache_clear()
    configured_user.cache_clear()
    current_branch.cache_clear()
    diff.cache_clear()
    log.cache_clear()
    Commit.get.cache_clear()
    PullRequest.get.cache_clear()
    GitHubRepo.get.cache_clear()


@pytest.fixture(autouse=True)
def run(mocker):
    return mocker.patch("gh_pr_upsert.git.run", autospec=True)
