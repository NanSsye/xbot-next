import React, { type ReactNode } from "react";

export type HeroStat = {
  label: string;
  value: string | number;
  tone?: "primary" | "secondary" | "amber" | "purple" | "neutral";
};

export type HeroAction = {
  label: string;
  icon?: React.ReactNode;
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
};

type IllustrationHeroProps = {
  title: string;
  badge?: string;
  tagline: string;
  illustrationSrc: string;
  illustrationAlt: string;
  stats?: HeroStat[];
  actions?: HeroAction[];
  children?: ReactNode;
  themeTone?: "terracotta" | "sage" | "amber" | "lavender" | "sky";
};

export function IllustrationHero({
  title,
  badge,
  tagline,
  illustrationSrc,
  illustrationAlt,
  stats = [],
  actions = [],
  children,
  themeTone = "terracotta",
}: IllustrationHeroProps) {
  return (
    <section className={`hero-banner hero-banner--${themeTone}`}>
      <div className="hero-banner__content">
        <div className="hero-banner__header">
          {badge && <span className="hero-banner__badge">{badge}</span>}
          <h1 className="hero-banner__title">{title}</h1>
        </div>
        <p className="hero-banner__tagline">{tagline}</p>

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

        {children}
      </div>

      <div className="hero-banner__art">
        <div className="hero-banner__art-glow" />
        <img
          src={illustrationSrc}
          alt={illustrationAlt}
          className="hero-banner__art-img"
          loading="eager"
        />
      </div>
    </section>
  );
}
