# To test — everything built but not yet tried by hand

Tick each one when you've tried it yourself. If something fails, leave it unticked and write what
happened underneath. Newest items go at the top of each section.

**Before any voice test:** restart the daemon (or quit and reopen Vox.app once it exists). The
daemon runs the code it was started with.

## From the app-overhaul session (2026-11-06 →)

### Vox.app: the new native app (start here)
Build it with `app/build.sh`, then open `app/build/Vox.app` (double-click it in Finder; don't run it
from Terminal, or Terminal gets the permissions instead of Vox). **Quit any Vox you started from a
terminal first** (`uv run vox --stop`). Vox.app starts its own.

- [ ] **First launch shows Setup** (not the main window). Step through: Welcome → Microphone (macOS prompt says "Vox") → Accessibility (System Settings opens; turn on Vox; the step ticks itself within a second of coming back) → Engine ("Vox is ready") → Brain ("Keep my current setup" → Test → "Working. Replied in 1.x s") → Try it (say "Hey Vox, what time is it?", which should tick) → Done → Open Vox.
- [ ] **Menu bar icon:** waveform while listening; click it for state, the type box, the last reply, Listening and Speak replies switches, Open Vox / Settings / Quit.
- [ ] **Type to Vox** from the menu bar and from Home: "open safari" works from idle; the reply appears under "Vox said".
- [ ] **Pause** (menu bar *Listening* off, or Home → Pause): the icon turns to a slashed mic and Vox ignores speech; typing still works.
- [ ] **Closing the window** keeps Vox in the menu bar. **Quit** stops the engine (unless *Settings → General → Stop listening when Vox quits* is off).
- [ ] **Restart Vox by voice** ("restart vox"): the app keeps showing it as running (it re-attaches).
- [ ] **"open dashboard" by voice** brings Vox.app forward instead of a browser tab; "close dashboard" hides it.
- [ ] **Home:** status hero, Recent, Quick Settings switches, Brains card, Try Saying tips. Everything lines up in light AND dark mode.
- [ ] **Conversation:** live bubbles as you talk; timestamps after gaps; type at the bottom.
- [ ] **Settings (⌘,):** tabs General · Listening · Voice · Brains · Control · Permissions · Advanced. Labels make sense to you? Model menus only show models for the chosen provider. "Takes effect after Vox restarts" appears where it applies. Advanced → Restart Engine, Show Data Folder, Open Log.
- [ ] **Permissions tab:** shows each permission's state with Allow… buttons.
- [ ] **Restart banner:** allow Screen Recording while Vox is running → Home shows "Restart Vox to finish turning on Screen Recording" → Restart clears it.
- [ ] **Personality:** click a tile to switch; change its voice; create, edit, delete a custom one.
- [ ] **Commands:** turn off a whole app group (its commands dim); double-click a command and add/remove a phrase; search "gmail". **Learning** tab: Approve / Reject a suggestion; Forget a learned command.
- [ ] **Vocabulary / Rules:** add with Return, edit inline (saves on click-away), toggle, delete (asks first).
- [ ] **Board:** drag a card to another list and onto a card mid-list (a known risk is the drag not starting); right-click → Move To; click to edit; delete asks first; "+" adds a list.
- [ ] **Reminders:** add a 1-minute timer (counts down, chimes); add a weekday alarm, cancel it with Delete.
- [ ] **Memory:** add a long-term memory, edit by double-click, Forget; step through days; search; Show in Finder.
- [ ] **Activity:** reply-time tiles, daily cost chart, By brain table, sort recent calls by reply time.
- [ ] **After a rebuild** (`app/build.sh` again) macOS may silently drop the Microphone/Accessibility grants (ad-hoc signing changes the app's identity). If Vox goes deaf after a rebuild, re-allow it in System Settings or run `tccutil reset All app.vox.mac`.
- [ ] **Downloadable build:** `app/build.sh --bundle-engine` then move `Vox.app` to another user account (or delete `~/Library/Application Support/Vox`) and launch: Setup installs Python + libraries (about 1 minute on a warm cache; first time longer, about 0.8 GB), then everything above works with no repo.

### Dragon-style typing (off by default): *Settings → Control → Typing*
Turn on "Type automatically in text fields", restart Vox, and watch `grep "\[auto\]" vox.log`.
- [ ] In Notes, "hello there" → typed (`[auto] typed`), with sensible spacing and capitals.
- [ ] "scratch that" → exactly that chunk disappears.
- [ ] "next tab please" → typed; then "that was a command" → the text is removed and it runs as a command.
- [ ] In Slack's message box, "next tab" (the whole utterance is a command) → runs (`tier=safe`).
- [ ] "close tab" in a text field → Vox asks "Close tab?"; "yes" closes it, "no" doesn't. "Vox, close tab" runs straight away.
- [ ] "I'll see you later" → typed, and Vox stays awake (no accidental exit).
- [ ] A password field → nothing typed, nothing logged.
- [ ] `[auto] focus … editable=` is right in Slack, Arc/Gmail, Cursor, Notes; Finder says False.
- [ ] Known limits: a pause of about 0.5 s splits dictation into chunks; background talk near a focused field gets typed; a bare "send"/"enter" in a chat app still sends.

### End-of-turn detection fixed (smart-turn)
- [ ] It was effectively broken: a double sigmoid scored every pause as "finished". Now fixed and upgraded to v3.2. Try *Settings → Listening → End of sentence → Smart* for a day. You should be cut off far less mid-thought, while finished sentences still end promptly. If it's worse than Silence, switch back and tell me.

### Commands no longer fire from the middle of sentences
- [ ] Say (in control mode) "I think we should go back to the old design" → NOT the Back button; it goes to the brain. "the previous window had the answer" → no window switch.
- [ ] Short commands still work: "next tab", "go back", "close this tab", "can you hide the sidebar for me", "switch to the next window".

### Board by voice: several at once, safer deletes
- [ ] "add buy milk, call the plumber and book flights to my to do list" → "Added 3 cards to To Do." and three cards appear.
- [ ] "move X and Y to done" → both move.
- [ ] A vague delete ("remove the call") → "Did you mean 'call plumber'? Say its name to delete it." Nothing is deleted. Naming it deletes it.

### Vision clicks double-check the label
- [ ] When "click Later" (or any plain label) has to fall back to looking at the screen and vision picks a differently-labelled button, Vox asks "Did you mean Got it?" instead of clicking. "yes" clicks it. `grep "labels disagree" vox.log`.

### Hold to talk (needs Vox.app)
- [ ] Hold **Right ⌥**: a soft *tink* after about 0.2 s. Say "open Safari", let go: a *pop*, and it runs immediately (no silence wait). Works from idle without saying "Vox" first.
- [ ] Pause mid-sentence while holding: you're NOT cut off.
- [ ] ⌥-shortcuts still work normally (e.g. ⌥E for an accent, ⌥-drag). Pressing another key cancels talking.
- [ ] Turn it off in *Settings → Listening → Hold to talk*.

### "David needs you": agent alerts
- [ ] Add the Notification hook from `mcp/README.md` to `~/.claude/settings.json`. In a Claude Code session that has registered a name ("your name is David, register yourself"), trigger a permission prompt → bubble **"David needs your OK to use Bash"**.
- [ ] Leave a session idle until Claude Code's idle notification fires → "David is waiting for you".
- [ ] *Settings → General → Coding agents* switches bubble / speech / off.

### Security
- [ ] Nothing to do by hand. The bridge now refuses state-changing requests that aren't JSON (stops any web page you visit from changing Vox's settings via localhost). If anything in the old browser dashboard stops saving, that's the cause; tell me.

### Claude subscription brain: about 4× faster
- [ ] Set *Settings → Brains → Quick replies → Provider* to **Claude subscription**, restart Vox, wait about 10 s, then give a command the parser doesn't know ("click the compose button"). Expect a reply in about 1 s (was about 5 s). `vox.log`'s usage line / Activity page shows the latency.
- [ ] Several commands in a row each stay about 1 s (a fresh client warms up between them).
- [ ] Check Activity Monitor: one idle `claude` process sits ready in the background. That's the pre-warmed client.
- [ ] Interrupt Vox mid-answer, then ask something else. The answer must be to the NEW question, never the old one.

### Pointing (Clicky-style)
- [ ] **"point at <something on screen>"**: a glowing ring flies from your mouse pointer to it, shows its name, pulses, and fades after ~4 s. Also: "circle the save button", "highlight settings", "where's the settings icon".
- [ ] **By number:** "show clickable", then "point at 14".
- [ ] **Brain uses it:** "show me where the export option is" (no fixed phrase) → `decision=POINT` in `vox.log`.
- [ ] **It never takes focus:** keep typing in another app while a ring is up; your keystrokes keep landing.
- [ ] **Multi-display:** point at something on your second screen; the ring appears on that screen.
- [ ] **An agent can point:** in Claude Code, ask it to use the vox-control `point` tool.
- [ ] Watch for "highlight the paragraph"-style requests now being treated as pointing (they'll say "couldn't find").

### Lighter listening (CPU)
- [ ] **CPU drop:** say "open Safari". `vox.log`'s `⏱ … stt` should be about 0.6 s (was about 1.1 s), and `cpu` well under 200%. Watch for rare app names now mis-transcribed (Whisper decodes greedily now).
- [ ] **Memory:** Vox now uses about 0.55 GB more RAM (`float32` Whisper). Check Activity Monitor after it loads. Undo: `whisper_compute_type="int8"`.
- [ ] **Kokoro replies** start no slower and use less CPU while speaking (4 threads instead of 10).
- [ ] **App switching:** switch Arc ↔ Slack ↔ Cursor. One `👁 window in view` per switch, and no `[focus] AX said…` lines. Then "click Settings" lands in the right app.
- [ ] **Idle speech gate (off by default):** after a day of use, `grep "voiced=" vox.log` on lines that matched a wake phrase. If they're all well above 150 ms, turn on *Settings → Listening → Idle speech gate* and check "hey vox" still wakes.

- [ ] **Small brain is faster (thinking off).** Use Vox normally for a while. Plain commands that reach the brain ("refresh page", "go to the github tab") should answer in about 1 s instead of 2-8 s. Watch for it acting on garbled speech it used to ask about. If that bothers you, set *Settings → Brains → Small brain thinking* to **On**.
- [ ] **No more empty replies from the small brain.** `grep "\[thinking\]" vox.log` shows any time thinking ran out of budget and Vox retried without it (only happens with thinking On).
- [ ] **Type to Vox:** `curl -s localhost:8765/api/say -H 'content-type: application/json' -d '{"text":"open safari"}'`. From idle it runs as a one-shot (no "vox" prefix needed). In control mode it's handled like a spoken command. `vox.log` shows `⌨  you (typed): …`.
- [ ] **Pause listening:** `curl -s localhost:8765/api/listening -H 'content-type: application/json' -d '{"paused":true}'`. Vox should ignore speech; typing still works. `{"paused":false}` resumes.
- [ ] **`/api/status` shows the real mode** (idle / control / assistant / dictation) instead of always "idle".

## Carried over from todo.md §0 (built earlier, still untested)

- [ ] **Desktop input primitives (#61)**: "scroll down", "scroll to the top", "page down", "press command S", "right click Submit", "double click 14", "drag 3 to 7", "set volume to 30". Watch `vox.log` for `decision=COMMAND … → actions.handle`.
- [ ] **"press submit" is NOT a keystroke**: it should fall through to the brain and click instead.
- [ ] **Background input delivery**: turn `input_background_delivery` on and try the gestures above with a different app focused. AppKit apps should work; Chromium/Electron likely ignore mouse events.
- [ ] **Board by voice**: "what's on my board" · "add a card to doing called test the board" · "move the test card to done" · "put a note on the test card that it worked" · "rename the test card to board verified" · "delete the board verified card" · "make a list called blocked" · "move the zzz card to done" (should fail gracefully).
- [ ] **TEACH by voice**: "whenever I say X, do Y". Look for `decision=TEACH` in `vox.log`.
- [ ] **Multi-step executor**: a request that needs two actions in a row.
- [ ] **Named agents (identity)**: in a CLI with the MCP wired, "your name is David, register yourself" → `whoami`, `list_agents`, speak ("David here …"), notify card labelled DAVID.
- [ ] **Speech queue vs the daemon**: Vox talking while an agent announces → no overlap, no long silence.
- [ ] **Notification bubble ✕ doesn't steal focus**: click the ✕ while typing elsewhere; focus stays put.
