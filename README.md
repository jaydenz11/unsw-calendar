# UNSW Deadlines calendar

A calendar feed of Jayden's UNSW quizzes, tests, assignments and exams. It's rebuilt every night from the deadline tracker after Claude checks Moodle.

Subscribe in Apple Calendar (or Google Calendar → Other calendars → From URL):

```
https://raw.githubusercontent.com/jaydenz11/unsw-calendar/main/unsw-deadlines.ics
```

- `unsw-deadlines.ics` is the feed. Don't edit it by hand, because the next nightly run overwrites it.
- `build_ics.py` turns a dump of the tracker database into the feed: `python3 -I build_ics.py <dump_dir> unsw-deadlines.ics`
