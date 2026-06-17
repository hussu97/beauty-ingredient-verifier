import { Database, ScanLine, Sparkles, SquareLibrary } from "lucide-react";
import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";

type Props = {
  children: ReactNode;
};

export default function Layout({ children }: Props) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand-lockup">
          <span className="brand-mark"><Sparkles size={18} /></span>
          <div>
            <strong>Beauty Verifier</strong>
            <span>Ingredient-aware product scan</span>
          </div>
        </Link>
        <nav className="nav-list" aria-label="Primary navigation">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
            <ScanLine size={18} />
            Scanner
          </NavLink>
          <NavLink to="/directory" className={({ isActive }) => (isActive ? "active" : "")}>
            <SquareLibrary size={18} />
            Directory
          </NavLink>
          <NavLink to="/admin" className={({ isActive }) => (isActive ? "active" : "")}>
            <Database size={18} />
            Admin
          </NavLink>
        </nav>
      </header>
      <main className="main-surface">{children}</main>
    </div>
  );
}
