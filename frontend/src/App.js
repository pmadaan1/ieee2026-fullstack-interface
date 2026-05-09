import { useState } from 'react';
import LiveView from './views/LiveView';
import LongTermView from './views/LongTermView';
import './App.css';

export default function App() {
  const [tab, setTab] = useState('live');     // 'live' | 'longterm'

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path d="M4 19 L9 12 L13 16 L20 6" stroke="currentColor" strokeWidth="2.4"
                    fill="none" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="20" cy="6" r="2" fill="currentColor" />
            </svg>
          </div>
          <span className="app-title">SteadyStep</span>
        </div>
        <nav className="tab-toggle" role="tablist">
          <button
            role="tab" aria-selected={tab === 'live'}
            className={`tab-btn${tab === 'live' ? ' tab-btn--active' : ''}`}
            onClick={() => setTab('live')}
          >Live</button>
          <button
            role="tab" aria-selected={tab === 'longterm'}
            className={`tab-btn${tab === 'longterm' ? ' tab-btn--active' : ''}`}
            onClick={() => setTab('longterm')}
          >Long-term</button>
        </nav>
      </header>

      {tab === 'live' ? <LiveView /> : <LongTermView />}
    </div>
  );
}
