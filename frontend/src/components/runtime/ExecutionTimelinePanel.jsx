import LogsPanel from "../monitor/LogsPanel";

export default function ExecutionTimelinePanel({ events = [] }) {
    return (
        <LogsPanel
            embedded
            events={events}
            showLevel={false}
            title="4 | Execution Timeline"
        />
    );
}
