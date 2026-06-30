import LogsPanel from "../monitor/LogsPanel";

const INITIAL_TIMELINE_EVENTS = [
    {
        time: "12:00:01",
        source: "TradingRuntime",
        state: "WAIT",
    },
];

export default function ExecutionTimelinePanel() {
    return (
        <LogsPanel
            embedded
            events={INITIAL_TIMELINE_EVENTS}
            showLevel={false}
            title="4 | Execution Timeline"
        />
    );
}
