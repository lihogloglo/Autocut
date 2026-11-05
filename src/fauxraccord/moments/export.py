"""Moments into Premiere, keeping the link to the rushes (no renamed clip, no new media).

One XML (a bin in Premiere) holding
  - « Moments · <kind> »  every moment of a kind end to end, with its seconds before and after
                          (a string-out), each clip marked with its rush and timecode;
  - « Moments · ✓ »       the moments ticked ✓ on the board, all kinds, in the order they happened;
  - « <rush> · moments »  the whole rush with a range marker on every moment, named after its kind;
  - « <rush> · sans … »   the rush with the dead time cut out (kinds marked `remove`: menus…), the
                          other moments marked on it: a first derush of a 10-hour session.
Which moments go in a string-out: those ticked ✓ if the kind has any, else all but the ✗.
Clipitems are written like the sync's (xmeml.sync_document): named after the file, same pathurl.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from ..i18n import tr
from ..media import MediaInfo, probe
from ..sync import Placed, SyncResult
from ..xmeml import add_marker, sync_document, write_document
from .rules import Moment, MomentType


def _tc(s: float) -> str:
    h, rem = divmod(int(s), 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}"


def chosen(moments: list[Moment], type_id: str) -> list[Moment]:
    mine = [m for m in moments if m.type == type_id]
    ticked = [m for m in mine if m.kept is True]
    return ticked or [m for m in mine if m.kept is not False]


def _sequence(infos: list[MediaInfo], fps: Fraction, files: dict[str, int], moments: list[Moment],
              name: str, uid: str, label) -> ET.Element | None:
    placed, pos = [], 0
    for m in moments:
        length = round((m.end - m.start) * float(fps))
        if length <= 0:
            continue
        placed.append(Placed(file=files[m.rush], lane=0, start=pos, length=length, src=m.start))
        pos += length
    if not placed:
        return None
    seq = sync_document(infos, SyncResult(fps.numerator, fps.denominator, placed, []), name, uid).find("sequence")
    for p, m in zip(placed, moments):
        add_marker(seq, label(m), p.start, p.start + p.length)
    return seq


def without(duration: float, cut: list[tuple[float, float]], shortest: float = 1.0) -> list[tuple[float, float]]:
    """The parts of [0, duration) outside the `cut` ranges, dropping leftovers under `shortest` s."""
    keep, t = [], 0.0
    for a, b in sorted(cut):
        if a - t >= shortest:
            keep.append((t, a))
        t = max(t, b)
    if duration - t >= shortest:
        keep.append((t, duration))
    return keep


def write(path: Path, moments: list[Moment], types: list[MomentType], project: str) -> list[str]:
    """Write the XML; returns the names of the sequences in it."""
    rushes = list(dict.fromkeys(m.rush for m in moments))
    if not rushes:
        raise ValueError(tr("Aucun moment à placer."))
    infos = [probe(Path(r)) for r in rushes]
    files = {r: k for k, r in enumerate(rushes)}
    fps = next((i.fps for i in infos if i.has_video), Fraction(30))
    names = {t.id: tr(t.name) for t in types}
    seqs: list[ET.Element] = []

    def where(m: Moment) -> str:
        return f"{Path(m.rush).stem} {_tc(m.anchor)}"

    for t in types:
        picked = chosen(moments, t.id)
        s = _sequence(infos, fps, files, picked, f"Moments · {names[t.id]}", f"m-{t.id}", where)
        if s is not None:
            seqs.append(s)
    ticked = sorted((m for m in moments if m.kept is True), key=lambda m: (files[m.rush], m.start))
    s = _sequence(infos, fps, files, ticked, "Moments · ✓", "m-kept",
                  lambda m: f"{names.get(m.type, m.type)} · {where(m)}")
    if s is not None:
        seqs.append(s)

    for k, (rush, info) in enumerate(zip(rushes, infos)):
        frames = round(info.duration * float(fps))
        root = sync_document(infos, SyncResult(fps.numerator, fps.denominator,
                                               [Placed(file=k, lane=0, start=0, length=frames, src=0.0)], []),
                             f"{Path(rush).stem} · moments", f"r{k}")
        seq = root.find("sequence")
        for m in moments:
            if m.rush == rush and m.kept is not False:
                add_marker(seq, f"{names.get(m.type, m.type)} {m.score:.0%}",
                           round(m.start * float(fps)), round(m.end * float(fps)))
        seqs.append(seq)

        dead = [t for t in types if t.remove]
        cut = [(m.start, m.end) for m in moments if m.rush == rush and m.kept is not False
               and any(m.type == t.id for t in dead)]
        if cut:
            kept = [Moment("", rush, a, b, a, 1.0) for a, b in without(info.duration, cut)]
            label = " ".join(names[t.id].lower() for t in dead)
            seq = _sequence(infos, fps, files, kept, f"{Path(rush).stem} · sans {label}", f"c{k}",
                            lambda m: f"{_tc(m.start)}–{_tc(m.end)}")
            if seq is not None:
                seqs.append(seq)
    write_document(path, seqs, project)
    return [s.findtext("name") for s in seqs]
