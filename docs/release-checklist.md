# Final release checks

Run this checklist on the packaged Windows build before calling a version ready
for normal users.

## Sign-in and process cleanup

- Complete ten sign-in/sign-out cycles in one app session.
- Cancel the sign-in window before logging in and confirm the app returns to a
  usable signed-out state.
- Close Average Assistant while the sign-in window is open.
- After each case, wait ten seconds and confirm no child Average Assistant or
  WebView2 processes from that run remain.
- Confirm sign-in never opens an Edge, Chrome, Brave, `about:blank`, or
  WebHelper tab.

## Memory, handles, and CPU

- Record the main app's memory and Windows handle count after it has been idle
  for one minute.
- Repeat ten sign-in/sign-out cycles, then let it idle for another minute.
- Memory must settle to no more than 50 MB above the starting value and must
  not grow steadily after each cycle.
- The Windows handle count must settle to no more than 50 above the starting
  value and must not grow steadily after each cycle.
- While idle, the app should remain near 0% CPU and should not perform repeated
  network requests.

## Roster workload

- Import and process a 1,000-bowler test roster.
- Clear the results, load another roster, and repeat the lookup.
- Confirm memory settles after clearing and that the interface remains usable.
- Confirm cancelling, closing, and retrying do not leave worker or WebView2
  processes running.

## Privacy and shutdown

- Sign out and verify that single lookup and roster lookup are disabled.
- Close and reopen the app and verify it starts signed out.
- Confirm no bearer token, password, cookie, or browser-storage file appears in
  the application folder, exports, logs, or temporary test files.
- Confirm only legacy app-owned login profiles are removed; normal browser
  profiles and data must remain untouched.

## Automated checks

- Run the test suite and code-quality checks.
- Build the Windows artifact and confirm the required WebView2 libraries are
  included.
- Treat any failed cleanup, steadily increasing resource use, or orphaned
  process as a release blocker.
