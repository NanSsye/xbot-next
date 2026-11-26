import React, { type ReactNode } from "react";

type HeroStat = {
  label: string;
  value: string | number;
  tone?: "primary" | "secondary" | "amber" | "purple" | "neutral";
};

type HeroAction = {
  label: string;
  icon?: React.ReactNode;
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
};

type IllustrationHeroProps = {
  title: string;
  tagline: string;
  stats?: HeroStat[];
  actions?: HeroAction[];
  children?: ReactNode;
};

export function PageHeading({
  title,
  tagline,
  stats = [],
  actions = [],
  children,
}: IllustrationHeroProps) {
  return (
    <header className="workspace-heading">
      <div className="hero-banner__content">
        <h1 className="hero-banner__title">{title}</h1>
        <p className="hero-banner__tagline">{tagline}</p>
        {children}
      </div>
      <div className="workspace-heading__actions">
        {stats.length > 0 && (
          <div className="hero-banner__stats">
            {stats.map((stat, i) => (
              <div key={i} className={`hero-stat hero-stat--${stat.tone || "neutral"}`}>
                <span className="hero-stat__value">{stat.value}</span>
                <span className="hero-stat__label">{stat.label}</span>
              </div>
            ))}
          </div>
        )}

        {actions.length > 0 && (
          <div className="hero-banner__actions">
            {actions.map((action, i) => (
              <button
                key={i}
                type="button"
                className={`hero-action-btn ${action.primary ? "hero-action-btn--primary" : "hero-action-btn--ghost"}`}
                onClick={action.onClick}
                disabled={action.disabled}
              >
                {action.icon}
                <span>{action.label}</span>
              </button>
            ))}
          </div>
        )}

      </div>
    </header>
  );
}
