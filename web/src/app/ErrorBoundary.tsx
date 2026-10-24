import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode; fallback?: ReactNode; label?: string };

/**
 * Catches a screen's render error and says so plainly: never a stack trace on screen.
 * The details go to the console for whoever is debugging.
 */
export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.warn(`StormCheck: ${this.props.label ?? "a screen"} fell back after an error`, error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    if (this.props.fallback) return this.props.fallback;
    return (
      <div role="alert" className="mx-auto max-w-[520px] py-24">
        <p className="micro text-slate-500">Unscheduled stop</p>
        <h1 className="display-tight mt-2 text-[28px] text-navy-900">This screen didn&rsquo;t load.</h1>
        <p className="mt-3 text-[15px] text-slate-500">Nothing was approved, posted or changed. The rest of StormCheck still works.</p>
        <div className="mt-6 flex gap-2">
          <button type="button" onClick={() => this.setState({ failed: false })} className="rounded-lg bg-navy-900 px-4 py-2 text-[14px] font-semibold text-cloud-50">
            Try again
          </button>
          <a href="/" className="rounded-lg px-4 py-2 text-[14px] text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-300)]">
            Back to Storm Run
          </a>
        </div>
      </div>
    );
  }
}
