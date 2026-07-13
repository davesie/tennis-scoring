# Feature ides for the tennis scoring webapp

## ~~Fix WTB Sync~~ ✓ Done
This message is confusing: ✓ Successfully synced 100 clubs! -> There are more than 100 clubs!!

## ~~Selecting players from list~~ ✓ Done
I want to be able to select two clubs and then select players from a list. For this feature the Fix WTB Sync needs to be done first, otherwise the data is not there for the feature. The order of the players are set by the list that is fetched from the wtb-tennis website. 

## ~~Fix player name cut off in the match view~~ ✓ Done
LK is now parsed out of player names and displayed as a smaller sub-line below the name. Font sizes reduced on mobile breakpoints.

## ~~Create Match day name automatically~~ ✓ Done
When both clubs are selected in the admin form, the match day name auto-fills as "Club A vs Club B". Only overwrites if the name is still the default or matches the auto-pattern.

## ~~Consistent design across all pages~~ ✓ Done
Scoreboard is now theme-aware (light in light mode, dark in dark mode) with elevation shadows. Admin pages adopt Broadcast Court design system. Primary color unified to BC blue, backgrounds consistent across all pages.

## ~~Substitute players for doubles~~ ✓ Done
Club IDs are now stored on match days. When setting up doubles pairings, the full club roster is fetched from the WTB player database and merged with the singles player list. Scorers can pick any player from the club, not just those who played singles. The "Edit Player Names" fallback still works for manual entry.

## ~~Remove the Match day field~~ ✓ Done
Match day name is now auto-generated as "Team A vs Team B" from the selected team names. The manual name input field has been removed from the admin form.

## ~~Team category selection for match days~~ ✓ Done
Category dropdown added to the Create Match Day form (Herren, Damen, Herren 30–70, Damen 30–50). The selected category filters the WTB player picker to only show players from that category (auto-scraping for non-Herren categories on first load). Category is stored on the match day and displayed as a badge in the admin list, archive, and matchday header.

## User accounts — for later (post test phase)
Current pilot setup: registration gated by a shared invite code
(`REGISTRATION_MODE=code` + `REGISTRATION_CODE`), no email infrastructure.
Revisit when opening up beyond ~15 users:
- **Password reset via email** — needs SMTP access (e.g. a transactional mail
  service); token link flow. Until then: the superadmin resets by env-sync
  (own account) or edits the DB; testers can simply register a fresh account.
- **Email verification** on signup (same SMTP dependency).
- **Admin user management UI** — list users, deactivate, reset password,
  promote; today only the superadmin exists as a special role.
- **Per-invite links** instead of one shared code (single-use, auditable).
