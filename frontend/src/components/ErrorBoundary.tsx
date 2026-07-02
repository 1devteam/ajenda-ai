import { Component, type ErrorInfo, type ReactNode } from "react";
import { Link } from "react-router-dom";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Unhandled UI error", error, info);
  }

  private handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.error) {
      return (
        <main className="page-shell narrow">
          <section className="panel auth-panel">
            <p className="eyebrow">Application error</p>
            <h1>Something went wrong</h1>
            <p>The Ajenda UI hit an unexpected error. Reload the page or return to the dashboard.</p>
            <div className="form-grid">
              <button type="button" className="primary-button" onClick={this.handleReload}>
                Reload page
              </button>
              <Link className="ghost-link" to="/dashboard">
                Go to dashboard
              </Link>
            </div>
            <div className="inline-error" role="alert">
              <pre>{this.state.error.message}</pre>
            </div>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}