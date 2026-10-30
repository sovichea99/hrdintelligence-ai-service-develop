# GitHub → Telegram notifications (topic: `Notification`)

This package contains everything needed. You only do the parts that require your own accounts.

```
.github/workflows/telegram-notify.yml   the workflow (copy into your repo as-is)
scripts/get-telegram-ids.sh             finds your chat ID + topic ID
scripts/test-telegram.sh                sends a test message to the topic
TELEGRAM_SETUP.md                       this guide
```

## Step 1. Create the bot (BotFather)

1. In Telegram, open **@BotFather** (verify the blue check mark).
2. Send `/newbot`, choose a display name, then a username ending in `bot`.
3. BotFather replies with a **token** (looks like `123456789:AA...`). Treat it like a password. Do not paste it in chats, issues, or code.
4. Recommended: send `/setjoingroups` → pick your bot → **Enable** (needed so it can be added to the group).
5. Privacy mode: the bot only needs to *send* messages, so leave the default. For the one-time ID lookup in Step 3 you can either mention the bot in your message (`@yourbot ping`) or temporarily run `/setprivacy` → **Disable**.

**Test:** the BotFather message shows your token and a `t.me/<username>` link.

## Step 2. Prepare the Telegram group and topic

1. The group must be a **supergroup with Topics enabled**. Open the group → **Edit (pencil)** → **Topics** → turn on. (Telegram converts the group to a supergroup automatically.)
2. Create a topic named exactly `Notification` (**Create Topic** in the group menu).
3. Add the bot: group → **Add Members** → search your bot's username.
4. Give it the minimum permissions. It only needs to post messages. Do **not** make it admin unless sending fails:
   - If the `Notification` topic is restricted, or members can't post by default, make the bot an admin with only **Manage Topics / post messages** rights enabled and everything else off.

**Test:** the bot appears in the member list.

## Step 3. Get the chat ID and topic (thread) ID

1. Post any message **inside the `Notification` topic** (e.g. `@yourbot ping`).
2. On your own computer (needs `curl` and `jq`):

   ```bash
   read -rs TELEGRAM_BOT_TOKEN && export TELEGRAM_BOT_TOKEN   # paste token, press Enter (it is hidden)
   chmod +x scripts/*.sh
   ./scripts/get-telegram-ids.sh
   ```

3. Find the entry whose *sample text* is your message. Note:
   - `chat id` (negative number starting `-100…`) → `TELEGRAM_CHAT_ID`
   - `thread id` → `TELEGRAM_THREAD_ID`

Alternative without scripts: right-click the message in the topic → **Copy Message Link**. A link like `https://t.me/c/1234567890/5/12` means chat ID `-1001234567890` (prefix `-100`) and thread ID `5`. (For the first message of a topic the thread ID equals that message's ID.)

> The General topic has no `message_thread_id`. Messages posted there appear as "none". Make sure you picked the `Notification` entry.

## Step 4. Send a manual test to the topic

```bash
export TELEGRAM_CHAT_ID="-100xxxxxxxxxx"   # from Step 3
export TELEGRAM_THREAD_ID="5"              # from Step 3
./scripts/test-telegram.sh
```

You should see the "Test notification" message inside the `Notification` topic, not in General.

## Step 5. Add secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret**. Create three:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token from BotFather |
| `TELEGRAM_CHAT_ID` | e.g. `-1001234567890` |
| `TELEGRAM_THREAD_ID` | e.g. `5` |

Or with the GitHub CLI (prompts for each value, nothing lands in shell history):

```bash
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
gh secret set TELEGRAM_THREAD_ID
```

Optional **variables** (same page, *Variables* tab):

| Name | Effect |
|---|---|
| `PUSH_BRANCHES` | Branches whose pushes are announced, comma-separated. Default: the default branch. `*` = all branches. |
| `NOTIFY_MERGE_PUSHES` | `true` to also announce the push created by merging a PR. Default off (avoids duplicate merge messages). |

## Step 6. Add the workflow to your repo

Copy `.github/workflows/telegram-notify.yml` into the **same path** in your repository, commit, and push to your default branch.

```bash
git add .github/workflows/telegram-notify.yml
git commit -m "Add Telegram notifications"
git push
```

Make sure **Settings → Actions → General** allows Actions to run.

## Step 7. Test every event

| Do this | Expect in `Notification` topic |
|---|---|
| Push a commit to the default branch | 🔨 commit list with short SHAs and links |
| Open a PR | 🟢 Pull request opened |
| Push another commit to the PR branch | 🔁 Pull request updated |
| Mark a draft PR ready for review | 👀 ready for review |
| Merge the PR | 🟣 Pull request merged (the merge push is suppressed) |
| Close a PR without merging | 🔴 closed without merging |

Check **Actions → Telegram Notify** to see each run.

## How duplicates are avoided

- Pushing to a PR branch fires both `push` and `pull_request: synchronize`. Pushes are announced only for `PUSH_BRANCHES` (default branch), so PR branch commits produce one "updated" message.
- Merging a PR pushes to the target branch. Pushes that look like a merge or squash commit (`Merge pull request #…` or title ending `(#123)`) are skipped because the "merged" message covers them. Rebase merges can't be detected this way, so you may see a commit message plus the merge message. Set `NOTIFY_MERGE_PUSHES=true` if you'd rather always get both.

## Security notes

- Token, chat ID, and thread ID live only in GitHub Actions Secrets. GitHub masks them in logs, and the workflow never echoes them.
- The workflow has `permissions: {}`: it can't read or write your repo.
- Commit messages and PR titles are untrusted input. They are read by `jq` from the event file and HTML-escaped, never interpolated into shell code.
- **Private repos:** nothing extra is required. Secrets stay in GitHub, and messages contain only titles, branch names, authors, and links (links require repo access to open). If the Telegram group has members outside the repo, remember titles and commit messages are visible to them.
- **Fork PRs:** GitHub withholds secrets from workflows triggered by forks, so fork PRs won't notify (the run fails with the "secrets must be set" error). This is intentional and safe. Don't switch to `pull_request_target` to work around it.
- If the token ever leaks: BotFather → `/revoke`, then update the GitHub secret.
- Limit who can edit workflows (branch protection / CODEOWNERS on `.github/`), since a workflow change can access secrets.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Bad Request: message thread not found` | Wrong `TELEGRAM_THREAD_ID`, or the topic was deleted. Redo Step 3. |
| `Bad Request: chat not found` | Wrong chat ID (needs the `-100` prefix), or the bot isn't in the group. |
| `Forbidden: bot was kicked / not a member` | Re-add the bot to the group. |
| `Forbidden: not enough rights to send text messages to the chat` | The bot can't post in that topic. Grant it admin with minimal rights, or allow members to send messages. |
| `Unauthorized` (401) | Token wrong or revoked. Update `TELEGRAM_BOT_TOKEN`. |
| `can't parse entities` | HTML parse failure. Unlikely since text is escaped. Open an issue with the run log. |
| Messages land in General | `TELEGRAM_THREAD_ID` is empty or unset. |
| `get-telegram-ids.sh` finds nothing | Post a new message in the topic after adding the bot; mention the bot or disable privacy mode; run `deleteWebhook` if one was set. |
| Workflow doesn't run | Workflow file must be on the default branch (for `push`) and Actions must be enabled. |
| Push messages missing for a branch | Add it to `PUSH_BRANCHES` (or use `*`). |
| HTTP 429 | Telegram rate limit; the workflow retries up to 3 times automatically. |
