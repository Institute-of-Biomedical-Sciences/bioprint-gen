%
; ====================================================================
;  BioprintGEN - Planet CNC G68 rotation-direction test (no extrusion)
;  Starts where the nozzle is, lifts 5 mm, makes one 10 mm rapid move
;  "along X" inside a frame rotated by +45 deg, then reports where it
;  really ended up and returns. Needs ~10 mm free to the right / up / down.
; ====================================================================
G21 G90
G1 Z[#<_z> + 5] F300 ;lift 5 mm
G09
#<sx> = #<_x>
#<sy> = #<_y>
(print,Start: X=#<sx> Y=#<sy>)
G52 X#<sx> Y#<sy>
G68 X0 Y0 R45
G0 X10 Y0
G69
G52.1
G09
#<dx> = [#<_x> - #<sx>]
#<dy> = [#<_y> - #<sy>]
(print,Moved by dX=#<dx> dY=#<dy>)
(print,Standard / counter-clockwise: dX=+7.07 dY=+7.07   Flipped / clockwise: dX=+7.07 dY=-7.07)
G0 X#<sx> Y#<sy>
(msg,Rotation test done - please note the two 'Moved by' numbers from the Output window)
M2
%
