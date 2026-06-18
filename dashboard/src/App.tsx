import { Routes, Route, useLocation } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { ThemeProvider } from "@/components/layout/theme";
import { PageTransition } from "@/components/animate/PageTransition";
import { Overview } from "@/pages/Overview";
import { TokenUsage } from "@/pages/TokenUsage";
import { Settings } from "@/pages/Settings";
import { Personalities } from "@/pages/Personalities";
import { AxTree } from "@/pages/AxTree";
import { Rules } from "@/pages/Rules";
import { Memory } from "@/pages/Memory";
import { Integrations } from "@/pages/Integrations";

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
