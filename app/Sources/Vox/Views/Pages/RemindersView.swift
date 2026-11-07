import SwiftUI

/// Timers, alarms and reminders, whether set by voice or here.
struct RemindersView: View {
    @Environment(AppModel.self) private var model
    @State private var reminders: [Reminder]?
    @State private var error: String?
    @State private var loadError: String?
    @State private var loadedAt = Date.distantPast
    @State private var adding = false
    @State private var selection = Set<String>()
    @State private var deleting: [Reminder] = []

    var body: some View {
        RequiresEngine {
            content
                .pageErrors($error, loadError: $loadError, loaded: reminders != nil)
                .refreshesPage(load)
                .toolbar {
                    ToolbarItem(placement: .primaryAction) {
                        Button("New Reminder", systemImage: "plus") { adding = true }.help("Set a timer, alarm or reminder")
                    }
                }
                .reloadsOnChange("reminders", api: model.api, load)   // set by voice → shows at once
                .task(id: nextFire) {
                    // Re-read just after the next one goes off: the engine drops a finished timer
                    // and moves a repeating one on, so the list never says "Due now" for long.
                    guard let next = nextFire else { return }
                    try? await Task.sleep(for: .seconds(max(0, next.timeIntervalSinceNow) + 2))
                    if !Task.isCancelled { await load() }
                }
                .sheet(isPresented: $adding) {
                    ReminderEditor { body in Task { await add(body) } }
                }
                .confirmationDialog(deleteTitle, isPresented: .init(get: { !deleting.isEmpty }, set: { if !$0 { deleting = [] } }),
                                    titleVisibility: .visible) {
                    Button(deleting.count == 1 ? "Cancel \(KindInfo(deleting[0].kind).name)" : "Cancel \(deleting.count) Items",
                           role: .destructive) { let r = deleting; Task { await delete(r) } }
                    Button("Keep", role: .cancel) {}
                } message: {
                    Text("It won't go off.")
                }
        }
    }

    /// The soonest time something goes off after the last load.
    private var nextFire: Date? {
        reminders?.compactMap(\.fireDate).filter { $0 > loadedAt }.min()
    }

    private var deleteTitle: String {
        guard let r = deleting.first else { return "" }
        return deleting.count == 1 ? "Cancel \u{201C}\(Self.title(r))\u{201D}?" : "Cancel \(deleting.count) items?"
    }

    @ViewBuilder
    private var content: some View {
        if let reminders {
            if reminders.isEmpty {
                ContentUnavailableView {
                    Label("Nothing scheduled", systemImage: "alarm")
                } description: {
                    Text("Timers, alarms, reminders and routines appear here. Try saying \u{201C}Remind me in 10 minutes to stretch\u{201D} or \u{201C}Every weekday at 7, tell me what's on my calendar and the weather.\u{201D}")
                } actions: {
                    Button("New Reminder") { adding = true }
                }
            } else {
                list(reminders)
            }
        } else if let loadError {
            LoadErrorView(title: "Couldn't load reminders", message: loadError) { Task { await load() } }
        } else {
            PageLoading()
        }
    }

    private func list(_ all: [Reminder]) -> some View {
        // Re-render every 30 s so "in 12 min" stays true.
        TimelineView(.periodic(from: .now, by: 30)) { tl in
            let groups = Self.group(all, now: tl.date)
            List(selection: $selection) {
                ForEach(groups, id: \.0) { title, items in
                    Section {
                        ForEach(items) { r in
                            ReminderRow(reminder: r, now: tl.date) { Task { await run(r) } }.tag(r.id)
                        }
                    } header: {
                        Text(title).pageSectionHeader()
                    }
                }
            }
            .listStyle(.inset)
            .contextMenu(forSelectionType: String.self) { ids in
                if ids.count == 1, let r = all.first(where: { ids.contains($0.id) }), r.kind == "routine" {
                    Button("Run Now") { Task { await run(r) } }
                }
                if !ids.isEmpty {
                    Button(ids.count == 1 ? "Cancel…" : "Cancel \(ids.count) Items…", role: .destructive) {
                        deleting = all.filter { ids.contains($0.id) }
                    }
                }
            }
            .onDeleteCommand { deleting = all.filter { selection.contains($0.id) } }
        }
    }

    /// Today (one-off, due before midnight), Later (one-off, after today), Repeating.
    static func group(_ all: [Reminder], now: Date) -> [(String, [Reminder])] {
        let sorted = all.sorted { ($0.fireDate ?? .distantFuture) < ($1.fireDate ?? .distantFuture) }
        let endOfToday = Calendar.current.startOfDay(for: now).addingTimeInterval(86_400)
        let routines = sorted.filter { $0.kind == "routine" }
        let rest = sorted.filter { $0.kind != "routine" }
        let once = rest.filter { !$0.isRepeating }
        let groups: [(String, [Reminder])] = [
            ("Routines", routines),
            ("Today", once.filter { ($0.fireDate ?? .distantFuture) < endOfToday }),
            ("Later", once.filter { ($0.fireDate ?? .distantFuture) >= endOfToday }),
            ("Repeating", rest.filter(\.isRepeating)),
        ]
        return groups.filter { !$0.1.isEmpty }
    }

    static func title(_ r: Reminder) -> String {
        let t = r.text.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? KindInfo(r.kind).name : t.prefix(1).uppercased() + t.dropFirst()
    }

    // MARK: Data

    private func load() async {
        do {
            let now = Date.now
            let fetched: [Reminder] = try await model.api.get("reminders")
            if fetched != reminders { reminders = fetched }   // the 10 s poll mostly finds no change
            loadedAt = now
            loadError = nil
        } catch { loadError = ErrorWords.reason(error) }
    }

    private func run(_ r: Reminder) async {
        do { try await model.api.post("reminders/\(r.id)/run") }
        catch { self.error = ErrorWords.message("Couldn't run that routine.", error) }
    }

    private func add(_ body: ReminderAddBody) async {
        do { try await model.api.send("reminders", body); error = nil }
        catch { self.error = ErrorWords.message("Couldn't set that \(KindInfo(body.kind).name.lowercased()).", error) }
        await load()
    }

    private func delete(_ items: [Reminder]) async {
        let ids = Set(items.map(\.id))
        withAnimation(.smooth) { reminders?.removeAll { ids.contains($0.id) } }
        selection.subtract(ids)
        do {
            for id in ids { try await model.api.delete("reminders/\(id)") }
            error = nil
        } catch { self.error = ErrorWords.message("Couldn't cancel that.", error) }
        await load()
    }
}

// MARK: Row

private struct ReminderRow: View {
    var reminder: Reminder
    var now: Date
    var onRun: () -> Void = {}

    var body: some View {
        let kind = KindInfo(reminder.kind)
        HStack(spacing: 12) {
            Image(systemName: kind.symbol)
                .font(.body.weight(.medium))
                .foregroundStyle(kind.tint)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(RemindersView.title(reminder)).lineLimit(2)
                Text(detail).font(.callout).foregroundStyle(.secondary)
            }
            Spacer(minLength: 12)
            if reminder.kind == "routine" {
                Button("Run Now", systemImage: "play.fill", action: onRun)
                    .labelStyle(.iconOnly).buttonStyle(.borderless)
                    .help("Run this routine now")
            }
            Text(relative)
                .font(.callout.monospacedDigit())
                .foregroundStyle(isDue ? Color.orange : Color.secondary)
        }
        .padding(.vertical, 4)
    }

    private var isDue: Bool { (reminder.fireDate ?? .distantFuture) <= now }

    /// "Reminder · today at 14:30", "Every weekday · tomorrow at 07:00". The kind is left out when
    /// it's already the title.
    private var detail: String {
        let named = !reminder.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        var parts = named ? [KindInfo(reminder.kind).name] : []
        if let rec = reminder.recurrence, !rec.isEmpty { parts.append(Recurrence.label(rec)) }
        if let d = reminder.fireDate { parts.append("\(day(d)) at \(d.formatted(date: .omitted, time: .shortened))") }
        let s = parts.joined(separator: " · ")
        return s.prefix(1).uppercased() + s.dropFirst()
    }

    private func day(_ d: Date) -> String {
        let cal = Calendar.current
        if cal.isDate(d, inSameDayAs: now) { return "today" }
        if let t = cal.date(byAdding: .day, value: 1, to: now), cal.isDate(d, inSameDayAs: t) { return "tomorrow" }
        if d.timeIntervalSince(now) < 6 * 86_400 { return d.formatted(.dateTime.weekday(.wide)) }
        return d.formatted(.dateTime.day().month(.abbreviated))
    }

    private var relative: String {
        guard let d = reminder.fireDate else { return "" }
        if isDue { return "Due now" }
        if d.timeIntervalSince(now) < 60 { return "in under a minute" }
        return d.formatted(.relative(presentation: .numeric, unitsStyle: .abbreviated))
    }
}

private struct KindInfo {
    var name: String
    var symbol: String
    var tint: Color

    init(_ kind: String) {
        switch kind {
        case "timer": (name, symbol, tint) = ("Timer", "timer", .orange)
        case "alarm": (name, symbol, tint) = ("Alarm", "alarm.fill", .red)
        case "routine": (name, symbol, tint) = ("Routine", "sparkles", .purple)
        default: (name, symbol, tint) = ("Reminder", "bell.fill", .accentColor)
        }
    }
}

private enum Recurrence {
    static let choices: [(String, String)] = [("", "Never"), ("daily", "Every day"), ("weekdays", "Every weekday"), ("weekly", "Every week")]

    /// "daily" → "Every day"; "every:1800" → "Every 30 min".
    static func label(_ rec: String) -> String {
        if let fixed = choices.first(where: { $0.0 == rec }) { return fixed.1 }
        if rec.hasPrefix("every:"), let secs = Double(rec.dropFirst(6)) {
            let f = DateComponentsFormatter()
            f.unitsStyle = .short
            f.allowedUnits = [.day, .hour, .minute]
            return "Every " + (f.string(from: secs) ?? "\(Int(secs)) s")
        }
        return rec.capitalized
    }
}

// MARK: Editor

private struct ReminderEditor: View {
    var onAdd: (ReminderAddBody) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var kind = "reminder"
    @State private var text = ""
    @State private var when = Calendar.current.date(byAdding: .minute, value: 30, to: .now) ?? .now
    @State private var minutes = 10
    @State private var repeats = ""

    var body: some View {
        Form {
            Section {
                Picker("Kind", selection: $kind) {
                    Text("Reminder").tag("reminder")
                    Text("Routine").tag("routine")
                    Text("Alarm").tag("alarm")
                    Text("Timer").tag("timer")
                }
                .pickerStyle(.segmented)
                TextField(kind == "reminder" ? "Remind me to" : kind == "routine" ? "Ask Vox to" : "Label", text: $text,
                          prompt: Text(kind == "reminder" ? "Stretch" : kind == "routine"
                                       ? "Tell me what's on my calendar and the weather" : "Optional"))
            }
            Section {
                if kind == "timer" {
                    LabeledContent("Duration") {
                        HStack(spacing: 6) {
                            TextField("Minutes", value: $minutes, format: .number)
                                .labelsHidden().multilineTextAlignment(.trailing).frame(width: 56)
                            Stepper("Minutes", value: $minutes, in: 1...1440).labelsHidden()
                            Text(minutes == 1 ? "minute" : "minutes").foregroundStyle(.secondary)
                        }
                    }
                } else {
                    DatePicker("When", selection: $when, in: Date.now..., displayedComponents: [.date, .hourAndMinute])
                    Picker("Repeat", selection: $repeats) {
                        ForEach(Recurrence.choices, id: \.0) { Text($0.1).tag($0.0) }
                    }
                }
            } footer: {
                Text(footer).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .frame(width: 440)
        .fixedSize(horizontal: false, vertical: true)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            ToolbarItem(placement: .confirmationAction) {
                Button("Add") { onAdd(makeBody()); dismiss() }
                    .disabled((kind == "reminder" || kind == "routine") && text.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    private var footer: String {
        switch kind {
        case "timer": "A chime plays \(minutes) \(minutes == 1 ? "minute" : "minutes") after you add it."
        case "alarm": "Vox plays an alarm sound and says it out loud."
        case "routine": "At that time Vox does it: briefs you from your calendar, weather and board, or runs a command like \u{201C}open my email\u{201D}."
        default: "Vox says it out loud, with a soft sound."
        }
    }

    private func makeBody() -> ReminderAddBody {
        let isTimer = kind == "timer"
        let fire = isTimer ? Date.now.addingTimeInterval(Double(max(minutes, 1)) * 60) : when
        return ReminderAddBody(kind: kind, text: text.trimmingCharacters(in: .whitespacesAndNewlines),
                               fireAt: LocalISO.string(fire), recurrence: isTimer || repeats.isEmpty ? nil : repeats)
    }
}
