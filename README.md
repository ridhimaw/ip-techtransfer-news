# IP & Tech Transfer Pulse

A news site that updates itself. Every 6 hours, GitHub collects headlines about patents, licensing, technology transfer and IP policy from public news feeds, filters and tags them, and publishes them on a free GitHub Pages site.

It shows only headlines, short snippets and links to the original publishers. It never copies full articles.

## What's in here

| File | What it does |
|---|---|
| `index.html` | The website: news feed, topic tabs, search |
| `news.json` | The stories (the robot rewrites this file) |
| `feeds.json` | **Your settings**: news sources, keywords, topic tags |
| `scripts/fetch_news.py` | The robot that reads feeds and updates `news.json` |
| `.github/workflows/update-news.yml` | Tells GitHub to run the robot every 6 hours |

Nothing needs installing. The script uses only built-in Python.

## Setup (about 10 minutes, all in the browser)

1. **Create a repo.** On GitHub, click **New repository**. Name it e.g. `ip-news`, set it to **Public**, and create it.
2. **Upload the files.** Click **uploading an existing file**, then drag in everything from this folder. Make sure the `.github` folder comes along: it's hidden on some computers, so if it's missing, create the file by hand with **Add file → Create new file**, type the name `.github/workflows/update-news.yml`, and paste in the contents. Click **Commit changes**.
3. **Let the robot save changes.** Go to **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions**, and click **Save**.
4. **Turn on the website.** Go to **Settings → Pages**. Under *Source* pick **Deploy from a branch**, then branch `main` and folder `/ (root)`, and click **Save**.
5. **Run it the first time.** Go to the **Actions** tab, enable workflows if asked, click **Update news → Run workflow**. It takes about a minute.
6. **Open your site** at `https://<your-username>.github.io/ip-news/`. Give Pages a minute or two after each update.

From then on it updates itself every 6 hours.

## Customising

All in `feeds.json`; edit it right on GitHub with the pencil icon.

- **Add a source:** add a line to `feeds`. Any RSS feed works. For a Google News search, use
  `https://news.google.com/rss/search?q=YOUR+WORDS+when:7d&hl=en-IN&gl=IN&ceid=IN:en`
  (put phrases in `%22quotes%22`).
- **Filter out junk:** a story must contain at least one word from `must_match_any`.
- **Topic tabs:** each entry in `tags` becomes a tab. A story gets the tag if it contains any of the listed words.
- **How long stories stay:** `keep_days` (default 45) and `max_items` (default 400).
- **How often it updates:** change the `cron` line in the workflow. `17 */6 * * *` means every 6 hours; `17 */3 * * *` would be every 3.

To change the site name, edit `site_title` and `site_tagline`. To change the footer credit, edit the bottom of `index.html`.

## If something goes wrong

- **Site says "Couldn't load the news file":** the first run hasn't finished. Check the Actions tab.
- **Action fails at "git push":** step 3 wasn't saved (read and write permissions).
- **A source shows `!!` in the Actions log:** that feed was down or blocked. The others still work, and it retries next run.
- **Updates stop after ~60 days:** GitHub pauses scheduled jobs on repos with no activity. Click **Enable workflow** on the Actions tab, or make any small commit.
