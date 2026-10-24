"use client";

import { Component, type ReactNode } from "react";

/**
 * Contains a failure to one part of the page: if the 3D model can't load (a flaky venue network,
 * a GPU that drops the context), the drawing and the rest of the story carry on with `fallback`.
 */
export class ErrorBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.warn("StormCheck: a section fell back after an error", error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
