from token_tv.providers.base import Account, Usage


class MockProvider:
    def fetch(self, account: Account) -> Usage:
        samples = {
            "claude_personal": Usage("mock", 29, 142, 4, 9876),
            "claude_work": Usage("mock", 61, 80, 22, 2400),
            "codex_personal": Usage("mock", 17, 95, 38, 5100),
        }
        return samples[account.key]
