import TradingDecisionCard from './TradingDecisionCard.jsx';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

describe('TradingDecisionCard', () => {
    it('renders trading cycle title', () => {
        render(<TradingDecisionCard decision={{}} />);
        expect(screen.getByText(/TRADING CYCLE/i)).toBeInTheDocument();
    });

    it('renders all 15 stages', () => {
        render(<TradingDecisionCard decision={{}} />);
        // 检查主要阶段是否存在
        const stageLabels = [
            'PARAMETER CONTEXT',
            'MARKET SELECTION',
            'MARKET DATA',
            'FEATURE BUILDER',
            'MICRO EDGE STRATEGY',
            'AI DECISION / REVIEW',
            'MONEY MANAGEMENT',
            'GOVERNANCE',
            'EXECUTION',
            'POSITION',
            'EXIT MONITORING',
            'SETTLEMENT',
            'POSITION CLOSED',
            'PERFORMANCE RECORD',
            'READY FOR NEXT TRADE',
        ];
        stageLabels.forEach(label => {
            expect(screen.getByText(label)).toBeInTheDocument();
        });
    });

    it('renders current activity panel', () => {
        render(<TradingDecisionCard decision={{}} />);
        expect(screen.getByText(/CURRENT ACTIVITY/i)).toBeInTheDocument();
        expect(screen.getByText(/CURRENT STAGE/i)).toBeInTheDocument();
        expect(screen.getByText(/CURRENT ACTION/i)).toBeInTheDocument();
        expect(screen.getByText(/SELECTED SYMBOL/i)).toBeInTheDocument();
        expect(screen.getByText(/NEXT STAGE/i)).toBeInTheDocument();
    });

    it('renders lower status panel', () => {
        render(<TradingDecisionCard decision={{}} />);
        expect(screen.getByText(/DECISION DETAILS/i)).toBeInTheDocument();
        expect(screen.getByText(/FINAL DECISION/i)).toBeInTheDocument();
        expect(screen.getByText(/CURRENT STATE/i)).toBeInTheDocument();
        expect(screen.getByText(/BLOCKED AT/i)).toBeInTheDocument();
        expect(screen.getByText(/REASON/i)).toBeInTheDocument();
    });

    it('displays selected symbol when available', () => {
        const symbol = 'BTC/USDT';
        render(<TradingDecisionCard decision={{
            stages: {
                market: {
                    symbol,
                },
            },
        }} />);
        expect(screen.getByText(symbol)).toBeInTheDocument();
    });

    it('handles position open state', () => {
        render(<TradingDecisionCard decision={{
            currentState: 'POSITION OPEN',
            stages: {
                execution: {
                    positionState: 'POSITION OPEN',
                },
            },
        }} />);
        // 检查是否显示POSITION阶段
        const positionStage = screen.getByText(/POSITION/i);
        expect(positionStage).toBeInTheDocument();
    });

    it('displays correct labels for Japanese users', () => {
        render(<TradingDecisionCard decision={{}} />);
        expect(screen.getByText(/トレーディングサイクル/i)).toBeInTheDocument();
    });
});
