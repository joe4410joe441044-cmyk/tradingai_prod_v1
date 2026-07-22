import { Component } from "react";

export default class MarketIntelligenceErrorBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false };
    }

    static getDerivedStateFromError() {
        return { hasError: true };
    }

    componentDidCatch(error, errorInfo) {
        console.error("MARKET INTELLIGENCE render error", error, errorInfo);
    }

    render() {
        if (this.state.hasError) {
            return (
                <main className="mi-page mi-error-boundary" role="alert">
                    <h1>MARKET INTELLIGENCE could not be displayed.</h1>
                    <p>Return to Dashboard and retry.</p>
                </main>
            );
        }

        return this.props.children;
    }
}
