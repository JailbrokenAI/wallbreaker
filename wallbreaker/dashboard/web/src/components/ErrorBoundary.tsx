import { Component, type ErrorInfo, type ReactNode } from "react";
import { appendActivity } from "../activityLog";
import { zh } from "../i18n/zh";

interface Props {
  children: ReactNode;
  label?: string;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    appendActivity(
      "system",
      `界面崩溃（${this.props.label || "应用"}）：${error.message}`,
      "error",
      { stack: error.stack, componentStack: info.componentStack },
    );
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="error-boundary card">
        <h3>{zh.errorBoundary.title}</h3>
        <p className="muted">
          {this.props.label ? `「${this.props.label}」${zh.errorBoundary.crashed}` : zh.errorBoundary.crashed}{" "}
          {zh.errorBoundary.retryHint}
        </p>
        <pre className="error-boundary-stack">{this.state.error.message}</pre>
        <div className="desktop-actions">
          <button
            type="button"
            className="primary-command"
            onClick={() => this.setState({ error: null })}
          >
            {zh.common.retry}
          </button>
          <button
            type="button"
            className="ghost-command"
            onClick={() => window.location.reload()}
          >
            {zh.errorBoundary.reload}
          </button>
        </div>
      </div>
    );
  }
}
