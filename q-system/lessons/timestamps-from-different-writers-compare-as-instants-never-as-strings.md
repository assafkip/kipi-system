---
id: timestamps-from-different-writers-compare-as-instants-never-as-strings
kind: pattern
title: Timestamps from different writers compare as instants, never as strings
date: 2026-09-10
---

An append-only log fed by more than one writer will carry ISO timestamps in more than one offset, and it will do so by construction rather than by mistake: a collector stamps `observed_at` from `datetime.now(utc)`, a responder stamps `at` from `datetime.now().astimezone()`, an upstream API hands over dates in its own zone. Every string is valid ISO 8601. Sorted or compared lexically they are wrong in a way no test written in one offset can see.

Measured 2026-09-10 on the first live typed round trip of a fresh system: the founder said an item was done, the bot confirmed it by name, and the item stayed open. The event row read `observed_at: 22:41:59+00:00`, the close read `at: 16:58:54-07:00` (seventeen minutes later in real time), and the closing condition was `closed_at >= observed_at` on the strings, so `"16:58" < "22:41"` made the close older than the observation. The same shape sat at ten more sites in the same package: reply and chat closes against message dates, an hourly since-last-run diff that would have re-pushed an open item every hour, a send rail that would have refused a reply because an older inbound message sorted after the draft, a yesterday count and a weekly window taken as the first ten characters of a UTC stamp, and every sort by `since` or `date`. All 177 tests were green. Their fixtures used one offset.

How to apply:

1. One parser for the whole package: `ts(s) -> float` (epoch seconds; a date-only string becomes local midnight; missing or unparseable is the oldest instant). Every `<`, `>=`, `max`, and every `sorted(key=...)` over a stamp goes through it. Grep for `("at")`, `("date")`, `observed_at` next to a comparison operator or a sort key and count the sites you did not know about.

2. Day boundaries go through one helper too: `local_date(stamp, now)` converts to the founder's offset before taking the date. A `[:10]` prefix of a UTC stamp puts a 19:30 local send on the next day.

3. Stamping consistently is not the fix. It narrows the window and the next writer widens it again; an upstream date arrives in whatever zone the upstream chose. Normalise at the comparison, where the invariant lives.

4. The test that catches it stamps one side in UTC and the other in a non-zero offset, with the real-time order the reverse of the lexical order. A fixture whose `NOW` is UTC, with a "local" close written as `NOW.isoformat()`, carries the same offset on both sides and passes for the wrong reason; the first draft of the regression test did exactly that and had to be restated with an explicit `-07:00`.

5. The exposure is proportional to the number of writers. A single-process store never shows it. It appears the day a second job, a second collector, or a second machine appends to the same file, which is also the day the log starts being useful.
