# LivingPortraitApp regression tests

These tests cover source-level regressions around CSRF protection, service restart
permissions, and appearance-setting restart feedback. They do not start Flask,
restart services, or require a Raspberry Pi.

From the repository root, run:

```bash
python3 -m unittest discover -s tests -v
```

The tests read the checked-out source files, so run them against the branch you
want to verify. These checks complement, but do not replace, an integration test
of an update and rollback on a Raspberry Pi.
