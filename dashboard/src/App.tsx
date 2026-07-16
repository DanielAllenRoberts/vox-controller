import { Routes, Route, useLocation } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { ThemeProvider } from "@/components/layout/theme";
import { PageTransition } from "@/components/animate/PageTransition";
import { Overview } from "@/pages/Overview";
import { Conversation } from "@/pages/Conversation";
import { Board } from "@/pages/Board";
import { Scheduler } from "@/pages/Scheduler";
import { TokenUsage } from "@/pages/TokenUsage";
import { Settings } from "@/pages/Settings";
import { Personalities } from "@/pages/Personalities";
import { AxTree } from "@/pages/AxTree";
import { Rules } from "@/pages/Rules";
import { Commands } from "@/pages/Commands";
import { Memory } from "@/pages/Memory";
import { Integrations } from "@/pages/Integrations";
import { Handbook } from "@/pages/Handbook";

export default function App() {
  const location = useLocation();
  return (
    <ThemeProvider>
      <Routes location={location}>
      <Route element={<AppShell />}>
        <Route
          index
          element={
            <PageTransition>
              <Overview />
            </PageTransition>
          }
        />
        <Route
          path="conversation"
          element={
            <PageTransition>
              <Conversation />
            </PageTransition>
          }
        />
        <Route
          path="board"
          element={
            <PageTransition>
              <Board />
            </PageTransition>
          }
        />
        <Route
          path="scheduler"
          element={
            <PageTransition>
              <Scheduler />
            </PageTransition>
          }
        />
        <Route
          path="usage"
          element={
            <PageTransition>
              <TokenUsage />
            </PageTransition>
          }
        />
        <Route
          path="settings"
          element={
            <PageTransition>
              <Settings />
            </PageTransition>
          }
        />
        <Route
          path="personalities"
          element={
            <PageTransition>
              <Personalities />
            </PageTransition>
          }
        />
        <Route
          path="axtree"
          element={
            <PageTransition>
              <AxTree />
            </PageTransition>
          }
        />
        <Route
          path="rules"
          element={
            <PageTransition>
              <Rules />
            </PageTransition>
          }
        />
        <Route
          path="commands"
          element={
            <PageTransition>
              <Commands />
            </PageTransition>
          }
        />
        <Route
          path="memory"
          element={
            <PageTransition>
              <Memory />
            </PageTransition>
          }
        />
        <Route
          path="integrations"
          element={
            <PageTransition>
              <Integrations />
            </PageTransition>
          }
        />
        <Route
          path="handbook"
          element={
            <PageTransition>
              <Handbook />
            </PageTransition>
          }
        />
        <Route
          path="*"
          element={
            <PageTransition>
              <Overview />
            </PageTransition>
          }
        />
        </Route>
      </Routes>
    </ThemeProvider>
  );
}
