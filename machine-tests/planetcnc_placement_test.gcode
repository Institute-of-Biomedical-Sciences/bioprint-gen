%
; ====================================================================
;  BioprintGEN - Planet CNC placement feature test (no extrusion)
;  Checks what the multi-well / device-template calibration relies on:
;    1. jogging during an M0 pause and reading the position afterwards
;    2. G52 offset + G68 rotation + subprogram call (M98 / O.. M99)
;    3. the tool-change G92 frame trick inside a G52 offset
;  Run it with NO plate / chip on the bed and the nozzle high enough
;  that 10 mm moves around the chosen points are safe. Only rapid moves
;  (G0) are made, and the nozzle first goes 5 mm UP from where you start.
;  Watch the Output window: every step prints what it measured.
; ====================================================================
(print,=== BioprintGEN placement test ===)
G21 G90
G1 Z[#<_z> + 5] F300 ;lift 5 mm before anything else

; ---------- 1. capture two points by jogging during a pause ----------
(msg,Step 1: jog the nozzle to point P1 (any free spot), then press Resume)
M0
G09
#<p1x> = #<_x>
#<p1y> = #<_y>
(print,P1 = X#<p1x> Y#<p1y>)
(msg,Step 1: now jog to point P2, about 20-50 mm away from P1 in any direction, then Resume)
M0
G09
#<p2x> = #<_x>
#<p2y> = #<_y>
(print,P2 = X#<p2x> Y#<p2y>)
#<dx> = [#<p2x> - #<p1x>]
#<dy> = [#<p2y> - #<p1y>]
#<d2> = [#<dx> * #<dx> + #<dy> * #<dy>]
#<ang> = ATAN2[#<dy>,#<dx>]
#<dist> = SQRT[#<d2>]
(print,Direction P1->P2 = #<ang> deg, distance = #<dist> mm)

; ---------- 2. offset + rotation + subprogram ----------
(msg,Step 2: the head will trace a 10 mm square (rapid, no extrusion). EXPECTED: it starts at P1 and its first side points towards P2. Resume to start)
M0
G52 X#<p1x> Y#<p1y>
G68 X0 Y0 R#<ang>
M98 P1000
(print,After the square: X=#<_x> Y=#<_y> (logical, expected 0 0))
G69
G52.1
(msg,Step 2 done: did the square start at P1 with its first side pointing at P2? Note the answer, then Resume)
M0

; ---------- 3. tool-change G92 trick inside a G52 offset ----------
(msg,Step 3: the head goes to P1, then shifts 5 mm in +X using the tool-change G92 trick, then traces a 10 mm line in +X. EXPECTED: the line runs from P1+5 to P1+15 in X. Resume to start)
M0
G52 X#<p1x> Y#<p1y>
G0 X0 Y0
#5 = #<_x>
#6 = #<_y>
G0 X[#<_x> + 5] Y[#<_y>]
G92 X#5 Y#6
(print,Inside the frame shift: logical X=#<_x> Y=#<_y> (expected 0 0))
G0 X10 Y0
G92 X[#<_x> + 5] Y[#<_y>]
(print,After removing the shift: logical X=#<_x> Y=#<_y> (expected 15 0))
G0 X0 Y0
G52.1
(print,Back at P1? Machine-side position X=#<_x> Y=#<_y> should equal P1)
(msg,Step 3 done: did the line run from P1+5 to P1+15 in X, and did the head return to P1? Test complete.)
M0
M2

O1000
G0 X0 Y0
G0 X10 Y0
G0 X10 Y10
G0 X0 Y10
G0 X0 Y0
M99
%
