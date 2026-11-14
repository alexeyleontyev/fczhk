"""Score model behind the betting odds: numpy and scipy only, small enough for the club server.

Goals of a team are Poisson with a log-rate built from the community ratings of the players on
the pitch: attack of its outfield players, defence of the opponents', a level for players without
a rating and a team-without-a-keeper effect. A match pace shared by both teams widens the total,
and draws get one renormalising parameter. The model is fitted by its posterior mode plus a
Laplace approximation, so prices carry parameter uncertainty; the pace is integrated out with
Gauss-Hermite quadrature. Scoring shares for player markets come from a penalised multinomial
over the players on the pitch.

The model was selected and checked walk-forward in the separate research project (Kolobok):
reading the ratings with a role correction -- a forward is rarely seen defending, so a learnt
share of the gap to his attack mark is added to his defence mark, and vice versa -- was the
largest single improvement over the ratings as given.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.polynomial.hermite_e import hermegauss
from scipy import optimize, special

K_MAX = 40  # goals per team covered by the score matrix
ON_PITCH = 7  # outfield places; a squad of n outfielders shares them equally
N_NODES = 9
SIGMA_S = 0.95  # prior scale of scoring propensities
SHARE_SHRINK = 0.85  # pulls scoring shares towards the average when pricing
RECENT_MATCHES = 30  # matches used for the share of goals with a named scorer
NAMES = (
    "mu",
    "beta_a",
    "beta_d",
    "pull_def",
    "pull_att",
    "guest_att",
    "guest_def",
    "kappa_none",
    "delta",
    "sigma_g",
)


@dataclass
class History:
    """Completed matches as arrays. Player index i refers to ``player_ids[i]``."""

    player_ids: list[int]
    r_att: np.ndarray  # (P,) community marks 0..5, NaN when unrated
    r_def: np.ndarray
    out_a: np.ndarray  # (G, P) share of the 7 outfield places, team A = white
    out_b: np.ndarray
    no_gk_a: np.ndarray  # (G,) 1 when team A had nobody regular in goal
    no_gk_b: np.ndarray
    goals_a: np.ndarray  # (G,)
    goals_b: np.ndarray
    members: np.ndarray  # (T, P) bool: everybody on the pitch per team-match
    member_gk: np.ndarray  # (T, P) bool: its goalkeeper
    team_goals: np.ndarray  # (T,) goals with a named scorer
    scored: np.ndarray  # (P,) goals with this player as the named scorer
    gk_scored: int  # goals scored by goalkeepers
    scorer_rate: float  # share of goals credited to a named scorer, recent matches


def normalisation(r_att: np.ndarray, r_def: np.ndarray) -> dict:
    ok = np.isfinite(r_att) & np.isfinite(r_def)
    if ok.sum() < 2:
        return dict(mean_att=0.0, std_att=1.0, mean_def=0.0, std_def=1.0, up_att=0.0, up_def=0.0)
    gap = r_att[ok] - r_def[ok]
    return dict(
        mean_att=float(r_att[ok].mean()),
        std_att=float(r_att[ok].std()) or 1.0,
        mean_def=float(r_def[ok].mean()),
        std_def=float(r_def[ok].std()) or 1.0,
        up_att=float(np.maximum(-gap, 0).mean()),
        up_def=float(np.maximum(gap, 0).mean()),
    )


def features(r_att, r_def, norm: dict, c_def, c_att):
    """Role-corrected, standardised marks; unrated players get 0. ``c_*`` may be arrays of
    draws, in which case the result is (draws, players)."""
    ok = np.isfinite(r_att) & np.isfinite(r_def)
    ra, rd = np.where(ok, r_att, 0.0), np.where(ok, r_def, 0.0)
    gap = ra - rd
    up_att, up_def = np.maximum(-gap, 0.0) * ok, np.maximum(gap, 0.0) * ok
    c_def, c_att = np.asarray(c_def)[..., None], np.asarray(c_att)[..., None]
    att = ra + c_att * up_att - (norm["mean_att"] + c_att * norm["up_att"])
    dfn = rd + c_def * up_def - (norm["mean_def"] + c_def * norm["up_def"])
    return att / norm["std_att"] * ok, dfn / norm["std_def"] * ok


def unpack(theta: np.ndarray) -> dict:
    theta = np.asarray(theta)
    p = {name: theta[..., i] for i, name in enumerate(NAMES)}
    p["pull_def"] = special.expit(p["pull_def"])
    p["pull_att"] = special.expit(p["pull_att"])
    p["sigma_g"] = np.exp(p["sigma_g"])
    return p


def poisson_logpmf(k, log_lam):
    return k * log_lam - np.exp(log_lam) - special.gammaln(k + 1)


class _Posterior:
    def __init__(self, h: History, norm: dict):
        self.h, self.norm = h, norm
        self.unrated = (~np.isfinite(h.r_att)).astype(float)
        self.mean_goals = max(float(np.mean(np.r_[h.goals_a, h.goals_b])), 0.5)
        nodes, weights = hermegauss(N_NODES)
        self.nodes, self.log_w = nodes, np.log(weights / weights.sum())
        self.k = np.arange(K_MAX + 1)
        self.x, self.y = h.goals_a.astype(float), h.goals_b.astype(float)
        self.draw = (h.goals_a == h.goals_b).astype(float)

    def __call__(self, theta: np.ndarray) -> float:
        p, h = unpack(theta), self.h
        f_att, f_def = features(h.r_att, h.r_def, self.norm, p["pull_def"], p["pull_att"])
        a = p["beta_a"] * f_att + p["guest_att"] * self.unrated
        d = p["beta_d"] * f_def + p["guest_def"] * self.unrated
        la = p["mu"] + h.out_a @ a - h.out_b @ d - p["kappa_none"] * h.no_gk_b
        lb = p["mu"] + h.out_b @ a - h.out_a @ d - p["kappa_none"] * h.no_gk_a
        shift = p["sigma_g"] * self.nodes[None, :]
        log_a, log_b = la[:, None] + shift, lb[:, None] + shift
        lp = poisson_logpmf(self.x[:, None], log_a) + poisson_logpmf(self.y[:, None], log_b)
        p_draw = np.exp(
            poisson_logpmf(self.k, log_a[..., None]) + poisson_logpmf(self.k, log_b[..., None])
        ).sum(-1)
        lp = lp + p["delta"] * self.draw[:, None] - np.log1p(np.expm1(p["delta"]) * p_draw)
        loglik = special.logsumexp(lp + self.log_w[None, :], axis=1).sum()
        logit_def, logit_att, log_sg = theta[3], theta[4], theta[9]
        logprior = (
            -0.5 * ((p["mu"] - np.log(self.mean_goals)) / 0.5) ** 2
            - 0.5 * (p["beta_a"] / 0.15) ** 2
            - 0.5 * (p["beta_d"] / 0.15) ** 2
            # Beta(1, 1) on each pull, in logit space
            - sum(np.logaddexp(0, -v) + np.logaddexp(0, v) for v in (logit_def, logit_att))
            - 0.5 * (p["guest_att"] / 0.1) ** 2
            - 0.5 * (p["guest_def"] / 0.1) ** 2
            - 0.5 * (p["kappa_none"] / 0.1) ** 2
            - 0.5 * (p["delta"] / 0.3) ** 2
            # HalfNormal(0.2) on the pace scale, in log space
            - 0.5 * (p["sigma_g"] / 0.2) ** 2
            + log_sg
        )
        return -(loglik + logprior)


def _hessian(f, x: np.ndarray, step: float = 1e-3) -> np.ndarray:
    n = len(x)
    h = np.zeros((n, n))
    f0 = f(x)
    eye = np.eye(n) * step
    for i in range(n):
        h[i, i] = (f(x + eye[i]) - 2 * f0 + f(x - eye[i])) / step**2
        for j in range(i):
            h[i, j] = h[j, i] = (
                f(x + eye[i] + eye[j])
                - f(x + eye[i] - eye[j])
                - f(x - eye[i] + eye[j])
                + f(x - eye[i] - eye[j])
            ) / (4 * step**2)
    return h


def _shares(h: History) -> tuple[np.ndarray, np.ndarray, float, float]:
    n_p = len(h.player_ids)
    if not h.team_goals.sum():
        return np.zeros(n_p), np.full(n_p, SIGMA_S), -2.0, 1.5
    gk = h.member_gk.astype(float)

    def probs(s, om):
        z = np.where(h.members, s[None, :] + om * gk, -np.inf)
        return np.exp(z - special.logsumexp(z, axis=1, keepdims=True))

    def objective(v):
        s, om = v[:-1], v[-1]
        z = np.where(h.members, s[None, :] + om * gk, -np.inf)
        ll = h.scored @ s + om * h.gk_scored - h.team_goals @ special.logsumexp(z, axis=1)
        return -(ll - 0.5 * (s @ s) / SIGMA_S**2 - 0.5 * ((om + 2.0) / 1.5) ** 2)

    def gradient(v):
        s, om = v[:-1], v[-1]
        pi = probs(s, om) * h.team_goals[:, None]
        gs = h.scored - pi.sum(0) - s / SIGMA_S**2
        go = h.gk_scored - (pi * gk).sum() - (om + 2.0) / 1.5**2
        return -np.r_[gs, go]

    res = optimize.minimize(objective, np.r_[np.zeros(n_p), -2.0], jac=gradient, method="L-BFGS-B")
    s, om = res.x[:-1], float(res.x[-1])
    pi = probs(s, om)
    info_s = (h.team_goals[:, None] * pi * (1 - pi) * h.members).sum(0) + 1 / SIGMA_S**2
    info_o = (h.team_goals[:, None] * pi * (1 - pi) * gk).sum() + 1 / 1.5**2
    return s, 1 / np.sqrt(info_s), om, float(1 / np.sqrt(info_o))


def fit(h: History) -> dict:
    """Fit on completed matches; the result is plain JSON-able data."""
    norm = normalisation(h.r_att, h.r_def)
    post = _Posterior(h, norm)
    start = np.array([np.log(post.mean_goals), 0.1, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, np.log(0.1)])
    res = optimize.minimize(post, start, method="L-BFGS-B")
    hess = _hessian(post, res.x)
    vals, vecs = np.linalg.eigh(0.5 * (hess + hess.T))
    cov = (vecs / np.maximum(vals, 1e-6)) @ vecs.T
    s, s_sd, om, om_sd = _shares(h)
    mode = unpack(res.x)
    return dict(
        version=1,
        names=list(NAMES),
        mode=[float(v) for v in res.x],
        cov=[[float(v) for v in row] for row in cov],
        norm=norm,
        shares={
            str(pid): [float(a), float(b)] for pid, a, b in zip(h.player_ids, s, s_sd, strict=True)
        },
        omega_s=[om, om_sd],
        scorer_rate=h.scorer_rate,
        n_matches=int(len(h.goals_a)),
        converged=bool(res.success),
        min_eigenvalue=float(vals.min()),
        summary={k: float(v) for k, v in mode.items()},
    )


@dataclass
class Simulation:
    """Score matrices per posterior draw and each team's scoring shares per draw."""

    mats: np.ndarray  # (S, K+1, K+1), [draw, white goals, black goals]
    shares: dict[str, tuple[list[int], np.ndarray]]  # team -> (player ids, (S, n) shares)
    lam_a: np.ndarray  # (S,) expected goals before the draw adjustment
    lam_b: np.ndarray


def simulate(
    model: dict, lineup: dict, ratings: dict, n_draws: int = 400, seed: int = 0
) -> Simulation:
    """``lineup``: team -> list of (player_id, is_keeper), keepers listed only when they are
    real players. ``ratings``: player_id -> (attack, defence) or None."""
    rng = np.random.default_rng(seed)
    theta = rng.multivariate_normal(np.array(model["mode"]), np.array(model["cov"]), size=n_draws)
    p = unpack(theta)

    def strengths(players):
        field = [pid for pid, gk in players if not gk]
        ra = np.array([ratings.get(pid, (np.nan, np.nan))[0] for pid in field], dtype=float)
        rd = np.array([ratings.get(pid, (np.nan, np.nan))[1] for pid in field], dtype=float)
        f_att, f_def = features(ra, rd, model["norm"], p["pull_def"], p["pull_att"])
        unrated = (~np.isfinite(ra)).astype(float)
        a = p["beta_a"][:, None] * f_att + p["guest_att"][:, None] * unrated
        d = p["beta_d"][:, None] * f_def + p["guest_def"][:, None] * unrated
        weight = ON_PITCH / max(len(field), 1)
        has_keeper = any(gk for _, gk in players)
        return weight * a.sum(1), weight * d.sum(1), has_keeper

    att_w, def_w, gk_w = strengths(lineup["white"])
    att_b, def_b, gk_b = strengths(lineup["black"])
    pace = rng.normal(size=n_draws) * p["sigma_g"]
    log_a = p["mu"] + att_w - def_b - p["kappa_none"] * (not gk_b) + pace
    log_b = p["mu"] + att_b - def_w - p["kappa_none"] * (not gk_w) + pace
    k = np.arange(K_MAX + 1)
    pmf_a = np.exp(poisson_logpmf(k, log_a[:, None]))
    pmf_b = np.exp(poisson_logpmf(k, log_b[:, None]))
    pmf_a /= pmf_a.sum(1, keepdims=True)
    pmf_b /= pmf_b.sum(1, keepdims=True)
    mats = pmf_a[:, :, None] * pmf_b[:, None, :]
    diag = np.arange(K_MAX + 1)
    mats[:, diag, diag] *= np.exp(p["delta"])[:, None]
    mats /= mats.sum(axis=(1, 2), keepdims=True)

    om, om_sd = model["omega_s"]
    omega = om + rng.normal(size=n_draws) * om_sd
    shares = {}
    for team in ("white", "black"):
        ids = [pid for pid, _ in lineup[team]]
        is_gk = np.array([gk for _, gk in lineup[team]], dtype=float)
        known = [model["shares"].get(str(pid), [0.0, SIGMA_S]) for pid in ids]
        s_hat = np.array([v[0] for v in known])
        s_sd = np.array([v[1] for v in known])
        s = s_hat + rng.normal(size=(n_draws, len(ids))) * s_sd
        w = np.exp(SHARE_SHRINK * s + omega[:, None] * is_gk)
        shares[team] = (ids, model["scorer_rate"] * w / w.sum(1, keepdims=True))
    return Simulation(mats=mats, shares=shares, lam_a=np.exp(log_a), lam_b=np.exp(log_b))
