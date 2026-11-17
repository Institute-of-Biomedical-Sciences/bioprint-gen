%
G21	G90 ;mm, absolute - plate positions

G1	A[#<_a> +0.05] ;ramp

; ===== plate calibration (guided) =====
G0	Z[#<_z> + 3] ;lift clear before calibration
(msg,Plate calibration, 4 points: 1 to 3 on the rim of well A1, spread around it, any order - then 4, the centre of well D6 on its floor. Jog to each and press Resume.)
(msg,Point 1 of 4: jog to the top edge of the rim of well A1. Its height sets the safe travel height. Then press Resume.)
M0
G09
#<pc_a1x> = #<_x>
#<pc_a1y> = #<_y>
#<pc_rz> = #<_z>
(msg,Point 2 of 4: another point on the rim of well A1, away from point 1. Then press Resume.)
M0
G09
#<pc_a2x> = #<_x>
#<pc_a2y> = #<_y>
(msg,Point 3 of 4: a third point on the rim of well A1, spread from the others. Then press Resume.)
M0
G09
#<pc_a3x> = #<_x>
#<pc_a3y> = #<_y>
(msg,Point 4 of 4: the centre of well D6, nozzle touching its floor. The floor height sets the first layer. Then press Resume.)
M0
G09
#<pc_bcx> = #<_x>
#<pc_bcy> = #<_y>
#<pc_fz> = #<_z>
#<pc_dy23> = [#<pc_a2y> - #<pc_a3y>]
#<pc_dy31> = [#<pc_a3y> - #<pc_a1y>]
#<pc_dy12> = [#<pc_a1y> - #<pc_a2y>]
#<pc_dx32> = [#<pc_a3x> - #<pc_a2x>]
#<pc_dx13> = [#<pc_a1x> - #<pc_a3x>]
#<pc_dx21> = [#<pc_a2x> - #<pc_a1x>]
#<pc_t1> = [#<pc_a1x> * #<pc_a1x>]
#<pc_t2> = [#<pc_a1y> * #<pc_a1y>]
#<pc_q1> = [#<pc_t1> + #<pc_t2>]
#<pc_t1> = [#<pc_a2x> * #<pc_a2x>]
#<pc_t2> = [#<pc_a2y> * #<pc_a2y>]
#<pc_q2> = [#<pc_t1> + #<pc_t2>]
#<pc_t1> = [#<pc_a3x> * #<pc_a3x>]
#<pc_t2> = [#<pc_a3y> * #<pc_a3y>]
#<pc_q3> = [#<pc_t1> + #<pc_t2>]
#<pc_t1> = [#<pc_a1x> * #<pc_dy23>]
#<pc_t2> = [#<pc_a2x> * #<pc_dy31>]
#<pc_t3> = [#<pc_a3x> * #<pc_dy12>]
#<pc_t4> = [#<pc_t1> + #<pc_t2>]
#<pc_t4> = [#<pc_t4> + #<pc_t3>]
#<pc_two> = 2
#<pc_d> = [#<pc_two> * #<pc_t4>]
#<pc_zero> = 0
#<pc_dz> = [#<pc_d> EQ #<pc_zero>]
#<pc_d> = [#<pc_d> + #<pc_dz>]
#<pc_t1> = [#<pc_q1> * #<pc_dy23>]
#<pc_t2> = [#<pc_q2> * #<pc_dy31>]
#<pc_t3> = [#<pc_q3> * #<pc_dy12>]
#<pc_t4> = [#<pc_t1> + #<pc_t2>]
#<pc_t4> = [#<pc_t4> + #<pc_t3>]
#<pc_acx> = [#<pc_t4> / #<pc_d>]
#<pc_t1> = [#<pc_q1> * #<pc_dx32>]
#<pc_t2> = [#<pc_q2> * #<pc_dx13>]
#<pc_t3> = [#<pc_q3> * #<pc_dx21>]
#<pc_t4> = [#<pc_t1> + #<pc_t2>]
#<pc_t4> = [#<pc_t4> + #<pc_t3>]
#<pc_acy> = [#<pc_t4> / #<pc_d>]
#<pc_mx> = [#<pc_bcx> - #<pc_acx>]
#<pc_my> = [#<pc_bcy> - #<pc_acy>]
#<pc_ma> = ATAN2[#<pc_my>,#<pc_mx>]
#<pc_na> = [0 - 30.963757]
#<pc_ang> = [#<pc_ma> - #<pc_na>]
#<pc_t1> = [#<pc_mx> * #<pc_mx>]
#<pc_t2> = [#<pc_my> * #<pc_my>]
#<pc_t3> = [#<pc_t1> + #<pc_t2>]
#<pc_md> = SQRT[#<pc_t3>]
#<pc_nd> = 112.537372
#<pc_ratio> = [#<pc_md> / #<pc_nd>]
#<pc_hundred> = 100
#<pc_t1> = [#<pc_ratio> * #<pc_hundred>]
#<pc_err> = [#<pc_t1> - #<pc_hundred>]
#<pc_sc> = 1
#<pc_ca> = COS[#<pc_ang>]
#<pc_sa> = SIN[#<pc_ang>]
#<pc_h1> = 0.2
#<pc_z1> = [#<pc_fz> + #<pc_h1>]
#<pc_top> = 0.4
#<pc_t1> = [#<pc_fz> + #<pc_top>]
#<pc_gt> = [#<pc_t1> GT #<pc_rz>]
#<pc_t2> = [#<pc_t1> - #<pc_rz>]
#<pc_t2> = [#<pc_t2> * #<pc_gt>]
#<pc_tz> = [#<pc_rz> + #<pc_t2>]
#<pc_clr> = 3
#<pc_tz> = [#<pc_tz> + #<pc_clr>]
(print,Calibrated: well A1 centre X=#<pc_acx> Y=#<pc_acy>, plate angle #<pc_ang> deg, spacing off by #<pc_err> percent, rim Z=#<pc_rz>, floor Z=#<pc_fz>)
(msg,Calibrated: well A1 centre X=#<pc_acx> Y=#<pc_acy>, plate angle #<pc_ang> deg, spacing off by #<pc_err> percent, rim Z=#<pc_rz>, floor Z=#<pc_fz>. Resume to print, Stop to cancel.)
M0
; ===== well A1 (1/4) =====
#<pc_lx> = 0
#<pc_ly> = 0
#<pc_t1> = [#<pc_lx> * #<pc_ca>]
#<pc_t2> = [#<pc_ly> * #<pc_sa>]
#<pc_t3> = [#<pc_t1> - #<pc_t2>]
#<pc_t4> = [#<pc_sc> * #<pc_t3>]
#<pc_wx> = [#<pc_acx> + #<pc_t4>]
#<pc_t1> = [#<pc_lx> * #<pc_sa>]
#<pc_t2> = [#<pc_ly> * #<pc_ca>]
#<pc_t3> = [#<pc_t1> + #<pc_t2>]
#<pc_t4> = [#<pc_sc> * #<pc_t3>]
#<pc_wy> = [#<pc_acy> + #<pc_t4>]
G0	Z#<pc_tz>
G52	X#<pc_wx>	Y#<pc_wy>
G68	X0	Y0	R#<pc_ang>
G0	X-1.97632	Y-1.97632
G0	Z#<pc_z1>
M98	P1000
G69
G52.1
G0	Z#<pc_tz>
(msg,Well A1 done - press Resume to continue)
M0
; ===== well A2 (2/4) =====
#<pc_lx> = 19.3
#<pc_ly> = 0
#<pc_t1> = [#<pc_lx> * #<pc_ca>]
#<pc_t2> = [#<pc_ly> * #<pc_sa>]
#<pc_t3> = [#<pc_t1> - #<pc_t2>]
#<pc_t4> = [#<pc_sc> * #<pc_t3>]
#<pc_wx> = [#<pc_acx> + #<pc_t4>]
#<pc_t1> = [#<pc_lx> * #<pc_sa>]
#<pc_t2> = [#<pc_ly> * #<pc_ca>]
#<pc_t3> = [#<pc_t1> + #<pc_t2>]
#<pc_t4> = [#<pc_sc> * #<pc_t3>]
#<pc_wy> = [#<pc_acy> + #<pc_t4>]
G0	Z#<pc_tz>
G52	X#<pc_wx>	Y#<pc_wy>
G68	X0	Y0	R#<pc_ang>
G0	X-1.97632	Y-1.97632
G0	Z#<pc_z1>
M98	P1000
G69
G52.1
G0	Z#<pc_tz>
(msg,Well A2 done - press Resume to continue)
M0
; ===== well B2 (3/4) =====
#<pc_lx> = 19.3
#<pc_ly> = [0 - 19.3]
#<pc_t1> = [#<pc_lx> * #<pc_ca>]
#<pc_t2> = [#<pc_ly> * #<pc_sa>]
#<pc_t3> = [#<pc_t1> - #<pc_t2>]
#<pc_t4> = [#<pc_sc> * #<pc_t3>]
#<pc_wx> = [#<pc_acx> + #<pc_t4>]
#<pc_t1> = [#<pc_lx> * #<pc_sa>]
#<pc_t2> = [#<pc_ly> * #<pc_ca>]
#<pc_t3> = [#<pc_t1> + #<pc_t2>]
#<pc_t4> = [#<pc_sc> * #<pc_t3>]
#<pc_wy> = [#<pc_acy> + #<pc_t4>]
G0	Z#<pc_tz>
G52	X#<pc_wx>	Y#<pc_wy>
G68	X0	Y0	R#<pc_ang>
G0	X-1.97632	Y-1.97632
G0	Z#<pc_z1>
M98	P1000
G69
G52.1
G0	Z#<pc_tz>
(msg,Well B2 done - press Resume to continue)
M0
; ===== well B1 (4/4) =====
#<pc_lx> = 0
#<pc_ly> = [0 - 19.3]
#<pc_t1> = [#<pc_lx> * #<pc_ca>]
#<pc_t2> = [#<pc_ly> * #<pc_sa>]
#<pc_t3> = [#<pc_t1> - #<pc_t2>]
#<pc_t4> = [#<pc_sc> * #<pc_t3>]
#<pc_wx> = [#<pc_acx> + #<pc_t4>]
#<pc_t1> = [#<pc_lx> * #<pc_sa>]
#<pc_t2> = [#<pc_ly> * #<pc_ca>]
#<pc_t3> = [#<pc_t1> + #<pc_t2>]
#<pc_t4> = [#<pc_sc> * #<pc_t3>]
#<pc_wy> = [#<pc_acy> + #<pc_t4>]
G0	Z#<pc_tz>
G52	X#<pc_wx>	Y#<pc_wy>
G68	X0	Y0	R#<pc_ang>
G0	X-1.97632	Y-1.97632
G0	Z#<pc_z1>
M98	P1000
G69
G52.1
G0	Z#<pc_tz>
G1	A[#<_a> -0.05] ;retract
G1	Z[#<_z> +2]	F300 ;go to safe height

; ===== BioprintGEN settings =====
; layer_height = 0.2
; first_layer_height = None
; line_width = 0.41
; strand_spacing = 1.0
; infill_angle = 0.0
; layer_rotation = 90.0
; infill_type = rectilinear_connected
; gyroid_period = 6.0
; infill_mode = spacing
; infill_percent = 40.0
; perimeters = 1
; rotate_start = True
; print_speed = 500.0
; travel_speed = 1600.0
; z_speed = 300.0
; dialect = planet_cnc
; drive = piston
; extruder_index = 1
; ext_per_10mm = 0.1
; ramp = 0.05
; flow_control = False
; valve_value = 1.0
; filament_area = 1.0
; tool_change_enabled = False
; extruder2_offset = (0.0, 0.0)
; extruder3_offset = (0.0, 0.0)
; flow_start_ramp = 0.0
; flow_end_retract = 0.0
; start_dwell = 0.0
; end_dwell = 0.0
; coast_distance = 0.0
; travel_lift = 0.0
; zero_xy_at_start = True
; safe_z = 2.0
; skirt = False
; skirt_distance = 2.0
; skirt_loops = 1
; write_settings_header = True
; gcode_line_ending = crlf
; minimize_crossings = True
; placement: 24-well plate, wells A1 A2 B2 B1, calibration: rim of A1 + centre of D6 (guided at print time), between wells: pause
; source: kind=cylinder, width=10, depth=10, height=0.4, diameter=6.0, stl_path=None
; BIOPRINTGEN_JSON {"version":1,"print_settings":{"layer_height":0.2,"first_layer_height":null,"layer_sections":[],"line_width":0.41,"strand_spacing":1.0,"infill_angle":0.0,"layer_rotation":90.0,"infill_type":"rectiline
; BIOPRINTGEN_JSON+ ar_connected","gyroid_period":6.0,"infill_mode":"spacing","infill_percent":40.0,"infill_sections":[],"components":[],"placement":{"enabled":true,"plate":{"name":"24-well","rows":4,"cols":6,"pitch_x":1
; BIOPRINTGEN_JSON+ 9.3,"pitch_y":19.3,"well_diameter":15.6,"well_depth":17.4,"a1_x":17.05,"a1_y":13.67},"wells":["A1","A2","B1","B2"],"rim_well":"A1","rim_points":[[0.0,0.0],[0.0,0.0],[0.0,0.0]],"rim_z":0.0,"centre_well
; BIOPRINTGEN_JSON+ ":"D6","centre_x":0.0,"centre_y":0.0,"floor_z":0.0,"use_measured_pitch":false,"clearance":3.0,"between":"pause","dwell":10.0,"guided":true},"perimeters":1,"rotate_start":true,"print_speed":500.0,"trav
; BIOPRINTGEN_JSON+ el_speed":1600.0,"z_speed":300.0,"dialect":"planet_cnc","custom_flavour":null,"drive":"piston","extruder_index":1,"ext_per_10mm":0.1,"ramp":0.05,"flow_control":false,"valve_value":1.0,"filament_area":
; BIOPRINTGEN_JSON+ 1.0,"tool_change_enabled":false,"extruder2_offset":[0.0,0.0],"extruder3_offset":[0.0,0.0],"tool_line_ranges":[],"flow_start_ramp":0.0,"flow_end_retract":0.0,"start_dwell":0.0,"end_dwell":0.0,"coast_di
; BIOPRINTGEN_JSON+ stance":0.0,"travel_lift":0.0,"zero_xy_at_start":true,"safe_z":2.0,"skirt":false,"skirt_distance":2.0,"skirt_loops":1,"start_gcode":"","end_gcode":"","write_settings_header":true,"gcode_line_ending":"
; BIOPRINTGEN_JSON+ crlf","minimize_crossings":true},"source":{"kind":"cylinder","width":10,"depth":10,"height":0.4,"diameter":6.0,"stl_path":null}}
; ===============================
M2

; ===== the print (subprogram 1000, called once per well) =====
O1000
; layer 0  z=0.2
G0	X-1.9763	Y-1.9763	F1600
G1	X-2.0709	Y-1.877	A[#<_a> +0.00137]	F500
G1	X-2.1605	Y-1.7731	A[#<_a> +0.00137]
G1	X-2.2449	Y-1.6649	A[#<_a> +0.00137]
G1	X-2.3239	Y-1.5528	A[#<_a> +0.00137]
G1	X-2.3973	Y-1.4369	A[#<_a> +0.00137]
G1	X-2.4649	Y-1.3175	A[#<_a> +0.00137]
G1	X-2.5266	Y-1.195	A[#<_a> +0.00137]
G1	X-2.5822	Y-1.0696	A[#<_a> +0.00137]
G1	X-2.6316	Y-0.9416	A[#<_a> +0.00137]
G1	X-2.6746	Y-0.8113	A[#<_a> +0.00137]
G1	X-2.7112	Y-0.6791	A[#<_a> +0.00137]
G1	X-2.7412	Y-0.5453	A[#<_a> +0.00137]
G1	X-2.7647	Y-0.4101	A[#<_a> +0.00137]
G1	X-2.7815	Y-0.274	A[#<_a> +0.00137]
G1	X-2.7916	Y-0.1371	A[#<_a> +0.00137]
G1	X-2.7949	Y0	A[#<_a> +0.00137]
G1	X-2.7916	Y0.1371	A[#<_a> +0.00137]
G1	X-2.7815	Y0.274	A[#<_a> +0.00137]
G1	X-2.7647	Y0.4101	A[#<_a> +0.00137]
G1	X-2.7412	Y0.5453	A[#<_a> +0.00137]
G1	X-2.7112	Y0.6791	A[#<_a> +0.00137]
G1	X-2.6746	Y0.8113	A[#<_a> +0.00137]
G1	X-2.6316	Y0.9416	A[#<_a> +0.00137]
G1	X-2.5822	Y1.0696	A[#<_a> +0.00137]
G1	X-2.5266	Y1.195	A[#<_a> +0.00137]
G1	X-2.4649	Y1.3175	A[#<_a> +0.00137]
G1	X-2.3973	Y1.4369	A[#<_a> +0.00137]
G1	X-2.3239	Y1.5528	A[#<_a> +0.00137]
G1	X-2.2449	Y1.6649	A[#<_a> +0.00137]
G1	X-2.1605	Y1.7731	A[#<_a> +0.00137]
G1	X-2.0709	Y1.877	A[#<_a> +0.00137]
G1	X-1.9763	Y1.9763	A[#<_a> +0.00137]
G1	X-1.877	Y2.0709	A[#<_a> +0.00137]
G1	X-1.7731	Y2.1605	A[#<_a> +0.00137]
G1	X-1.6649	Y2.2449	A[#<_a> +0.00137]
G1	X-1.5528	Y2.3239	A[#<_a> +0.00137]
G1	X-1.4369	Y2.3973	A[#<_a> +0.00137]
G1	X-1.3175	Y2.4649	A[#<_a> +0.00137]
G1	X-1.195	Y2.5266	A[#<_a> +0.00137]
G1	X-1.0696	Y2.5822	A[#<_a> +0.00137]
G1	X-0.9416	Y2.6316	A[#<_a> +0.00137]
G1	X-0.8113	Y2.6746	A[#<_a> +0.00137]
G1	X-0.6791	Y2.7112	A[#<_a> +0.00137]
G1	X-0.5453	Y2.7412	A[#<_a> +0.00137]
G1	X-0.4101	Y2.7647	A[#<_a> +0.00137]
G1	X-0.274	Y2.7815	A[#<_a> +0.00137]
G1	X-0.1371	Y2.7916	A[#<_a> +0.00137]
G1	X0	Y2.7949	A[#<_a> +0.00137]
G1	X0.1371	Y2.7916	A[#<_a> +0.00137]
G1	X0.274	Y2.7815	A[#<_a> +0.00137]
G1	X0.4101	Y2.7647	A[#<_a> +0.00137]
G1	X0.5453	Y2.7412	A[#<_a> +0.00137]
G1	X0.6791	Y2.7112	A[#<_a> +0.00137]
G1	X0.8113	Y2.6746	A[#<_a> +0.00137]
G1	X0.9416	Y2.6316	A[#<_a> +0.00137]
G1	X1.0696	Y2.5822	A[#<_a> +0.00137]
G1	X1.195	Y2.5266	A[#<_a> +0.00137]
G1	X1.3175	Y2.4649	A[#<_a> +0.00137]
G1	X1.4369	Y2.3973	A[#<_a> +0.00137]
G1	X1.5528	Y2.3239	A[#<_a> +0.00137]
G1	X1.6649	Y2.2449	A[#<_a> +0.00137]
G1	X1.7731	Y2.1605	A[#<_a> +0.00137]
G1	X1.877	Y2.0709	A[#<_a> +0.00137]
G1	X1.9763	Y1.9763	A[#<_a> +0.00137]
G1	X2.0709	Y1.877	A[#<_a> +0.00137]
G1	X2.1605	Y1.7731	A[#<_a> +0.00137]
G1	X2.2449	Y1.6649	A[#<_a> +0.00137]
G1	X2.3239	Y1.5528	A[#<_a> +0.00137]
G1	X2.3973	Y1.4369	A[#<_a> +0.00137]
G1	X2.4649	Y1.3175	A[#<_a> +0.00137]
G1	X2.5266	Y1.195	A[#<_a> +0.00137]
G1	X2.5822	Y1.0696	A[#<_a> +0.00137]
G1	X2.6316	Y0.9416	A[#<_a> +0.00137]
G1	X2.6746	Y0.8113	A[#<_a> +0.00137]
G1	X2.7112	Y0.6791	A[#<_a> +0.00137]
G1	X2.7412	Y0.5453	A[#<_a> +0.00137]
G1	X2.7647	Y0.4101	A[#<_a> +0.00137]
G1	X2.7815	Y0.274	A[#<_a> +0.00137]
G1	X2.7916	Y0.1371	A[#<_a> +0.00137]
G1	X2.7949	Y0	A[#<_a> +0.00137]
G1	X2.7916	Y-0.1371	A[#<_a> +0.00137]
G1	X2.7815	Y-0.274	A[#<_a> +0.00137]
G1	X2.7647	Y-0.4101	A[#<_a> +0.00137]
G1	X2.7412	Y-0.5453	A[#<_a> +0.00137]
G1	X2.7112	Y-0.6791	A[#<_a> +0.00137]
G1	X2.6746	Y-0.8113	A[#<_a> +0.00137]
G1	X2.6316	Y-0.9416	A[#<_a> +0.00137]
G1	X2.5822	Y-1.0696	A[#<_a> +0.00137]
G1	X2.5266	Y-1.195	A[#<_a> +0.00137]
G1	X2.4649	Y-1.3175	A[#<_a> +0.00137]
G1	X2.3973	Y-1.4369	A[#<_a> +0.00137]
G1	X2.3239	Y-1.5528	A[#<_a> +0.00137]
G1	X2.2449	Y-1.6649	A[#<_a> +0.00137]
G1	X2.1605	Y-1.7731	A[#<_a> +0.00137]
G1	X2.0709	Y-1.877	A[#<_a> +0.00137]
G1	X1.9763	Y-1.9763	A[#<_a> +0.00137]
G1	X1.877	Y-2.0709	A[#<_a> +0.00137]
G1	X1.7731	Y-2.1605	A[#<_a> +0.00137]
G1	X1.6649	Y-2.2449	A[#<_a> +0.00137]
G1	X1.5528	Y-2.3239	A[#<_a> +0.00137]
G1	X1.4369	Y-2.3973	A[#<_a> +0.00137]
G1	X1.3175	Y-2.4649	A[#<_a> +0.00137]
G1	X1.195	Y-2.5266	A[#<_a> +0.00137]
G1	X1.0696	Y-2.5822	A[#<_a> +0.00137]
G1	X0.9416	Y-2.6316	A[#<_a> +0.00137]
G1	X0.8113	Y-2.6746	A[#<_a> +0.00137]
G1	X0.6791	Y-2.7112	A[#<_a> +0.00137]
G1	X0.5453	Y-2.7412	A[#<_a> +0.00137]
G1	X0.4101	Y-2.7647	A[#<_a> +0.00137]
G1	X0.274	Y-2.7815	A[#<_a> +0.00137]
G1	X0.1371	Y-2.7916	A[#<_a> +0.00137]
G1	X0	Y-2.7949	A[#<_a> +0.00137]
G1	X-0.1371	Y-2.7916	A[#<_a> +0.00137]
G1	X-0.274	Y-2.7815	A[#<_a> +0.00137]
G1	X-0.4101	Y-2.7647	A[#<_a> +0.00137]
G1	X-0.5453	Y-2.7412	A[#<_a> +0.00137]
G1	X-0.6791	Y-2.7112	A[#<_a> +0.00137]
G1	X-0.8113	Y-2.6746	A[#<_a> +0.00137]
G1	X-0.9416	Y-2.6316	A[#<_a> +0.00137]
G1	X-1.0696	Y-2.5822	A[#<_a> +0.00137]
G1	X-1.195	Y-2.5266	A[#<_a> +0.00137]
G1	X-1.3175	Y-2.4649	A[#<_a> +0.00137]
G1	X-1.4369	Y-2.3973	A[#<_a> +0.00137]
G1	X-1.5528	Y-2.3239	A[#<_a> +0.00137]
G1	X-1.6649	Y-2.2449	A[#<_a> +0.00137]
G1	X-1.7731	Y-2.1605	A[#<_a> +0.00137]
G1	X-1.877	Y-2.0709	A[#<_a> +0.00137]
G1	X-1.9763	Y-1.9763	A[#<_a> +0.00137]
G0	X-1.8536	Y-1.5	F1600
G1	X1.8536	Y-1.5	A[#<_a> +0.03707]	F500
G1	X2.3312	Y-0.5	A[#<_a> +0.01108]
G1	X-2.3312	Y-0.5	A[#<_a> +0.04662]
G1	X-2.3312	Y0.5	A[#<_a> +0.01]
G1	X2.3312	Y0.5	A[#<_a> +0.04662]
G1	X1.8536	Y1.5	A[#<_a> +0.01108]
G1	X-1.8536	Y1.5	A[#<_a> +0.03707]

G1	Z[#<_z> +0.2]	F300

; layer 1  z=0.4
G0	X1.9763	Y-1.9763	F1600
G1	X1.877	Y-2.0709	A[#<_a> +0.00137]	F500
G1	X1.7731	Y-2.1605	A[#<_a> +0.00137]
G1	X1.6649	Y-2.2449	A[#<_a> +0.00137]
G1	X1.5528	Y-2.3239	A[#<_a> +0.00137]
G1	X1.4369	Y-2.3973	A[#<_a> +0.00137]
G1	X1.3175	Y-2.4649	A[#<_a> +0.00137]
G1	X1.195	Y-2.5266	A[#<_a> +0.00137]
G1	X1.0696	Y-2.5822	A[#<_a> +0.00137]
G1	X0.9416	Y-2.6316	A[#<_a> +0.00137]
G1	X0.8113	Y-2.6746	A[#<_a> +0.00137]
G1	X0.6791	Y-2.7112	A[#<_a> +0.00137]
G1	X0.5453	Y-2.7412	A[#<_a> +0.00137]
G1	X0.4101	Y-2.7647	A[#<_a> +0.00137]
G1	X0.274	Y-2.7815	A[#<_a> +0.00137]
G1	X0.1371	Y-2.7916	A[#<_a> +0.00137]
G1	X0	Y-2.7949	A[#<_a> +0.00137]
G1	X-0.1371	Y-2.7916	A[#<_a> +0.00137]
G1	X-0.274	Y-2.7815	A[#<_a> +0.00137]
G1	X-0.4101	Y-2.7647	A[#<_a> +0.00137]
G1	X-0.5453	Y-2.7412	A[#<_a> +0.00137]
G1	X-0.6791	Y-2.7112	A[#<_a> +0.00137]
G1	X-0.8113	Y-2.6746	A[#<_a> +0.00137]
G1	X-0.9416	Y-2.6316	A[#<_a> +0.00137]
G1	X-1.0696	Y-2.5822	A[#<_a> +0.00137]
G1	X-1.195	Y-2.5266	A[#<_a> +0.00137]
G1	X-1.3175	Y-2.4649	A[#<_a> +0.00137]
G1	X-1.4369	Y-2.3973	A[#<_a> +0.00137]
G1	X-1.5528	Y-2.3239	A[#<_a> +0.00137]
G1	X-1.6649	Y-2.2449	A[#<_a> +0.00137]
G1	X-1.7731	Y-2.1605	A[#<_a> +0.00137]
G1	X-1.877	Y-2.0709	A[#<_a> +0.00137]
G1	X-1.9763	Y-1.9763	A[#<_a> +0.00137]
G1	X-2.0709	Y-1.877	A[#<_a> +0.00137]
G1	X-2.1605	Y-1.7731	A[#<_a> +0.00137]
G1	X-2.2449	Y-1.6649	A[#<_a> +0.00137]
G1	X-2.3239	Y-1.5528	A[#<_a> +0.00137]
G1	X-2.3973	Y-1.4369	A[#<_a> +0.00137]
G1	X-2.4649	Y-1.3175	A[#<_a> +0.00137]
G1	X-2.5266	Y-1.195	A[#<_a> +0.00137]
G1	X-2.5822	Y-1.0696	A[#<_a> +0.00137]
G1	X-2.6316	Y-0.9416	A[#<_a> +0.00137]
G1	X-2.6746	Y-0.8113	A[#<_a> +0.00137]
G1	X-2.7112	Y-0.6791	A[#<_a> +0.00137]
G1	X-2.7412	Y-0.5453	A[#<_a> +0.00137]
G1	X-2.7647	Y-0.4101	A[#<_a> +0.00137]
G1	X-2.7815	Y-0.274	A[#<_a> +0.00137]
G1	X-2.7916	Y-0.1371	A[#<_a> +0.00137]
G1	X-2.7949	Y0	A[#<_a> +0.00137]
G1	X-2.7916	Y0.1371	A[#<_a> +0.00137]
G1	X-2.7815	Y0.274	A[#<_a> +0.00137]
G1	X-2.7647	Y0.4101	A[#<_a> +0.00137]
G1	X-2.7412	Y0.5453	A[#<_a> +0.00137]
G1	X-2.7112	Y0.6791	A[#<_a> +0.00137]
G1	X-2.6746	Y0.8113	A[#<_a> +0.00137]
G1	X-2.6316	Y0.9416	A[#<_a> +0.00137]
G1	X-2.5822	Y1.0696	A[#<_a> +0.00137]
G1	X-2.5266	Y1.195	A[#<_a> +0.00137]
G1	X-2.4649	Y1.3175	A[#<_a> +0.00137]
G1	X-2.3973	Y1.4369	A[#<_a> +0.00137]
G1	X-2.3239	Y1.5528	A[#<_a> +0.00137]
G1	X-2.2449	Y1.6649	A[#<_a> +0.00137]
G1	X-2.1605	Y1.7731	A[#<_a> +0.00137]
G1	X-2.0709	Y1.877	A[#<_a> +0.00137]
G1	X-1.9763	Y1.9763	A[#<_a> +0.00137]
G1	X-1.877	Y2.0709	A[#<_a> +0.00137]
G1	X-1.7731	Y2.1605	A[#<_a> +0.00137]
G1	X-1.6649	Y2.2449	A[#<_a> +0.00137]
G1	X-1.5528	Y2.3239	A[#<_a> +0.00137]
G1	X-1.4369	Y2.3973	A[#<_a> +0.00137]
G1	X-1.3175	Y2.4649	A[#<_a> +0.00137]
G1	X-1.195	Y2.5266	A[#<_a> +0.00137]
G1	X-1.0696	Y2.5822	A[#<_a> +0.00137]
G1	X-0.9416	Y2.6316	A[#<_a> +0.00137]
G1	X-0.8113	Y2.6746	A[#<_a> +0.00137]
G1	X-0.6791	Y2.7112	A[#<_a> +0.00137]
G1	X-0.5453	Y2.7412	A[#<_a> +0.00137]
G1	X-0.4101	Y2.7647	A[#<_a> +0.00137]
G1	X-0.274	Y2.7815	A[#<_a> +0.00137]
G1	X-0.1371	Y2.7916	A[#<_a> +0.00137]
G1	X0	Y2.7949	A[#<_a> +0.00137]
G1	X0.1371	Y2.7916	A[#<_a> +0.00137]
G1	X0.274	Y2.7815	A[#<_a> +0.00137]
G1	X0.4101	Y2.7647	A[#<_a> +0.00137]
G1	X0.5453	Y2.7412	A[#<_a> +0.00137]
G1	X0.6791	Y2.7112	A[#<_a> +0.00137]
G1	X0.8113	Y2.6746	A[#<_a> +0.00137]
G1	X0.9416	Y2.6316	A[#<_a> +0.00137]
G1	X1.0696	Y2.5822	A[#<_a> +0.00137]
G1	X1.195	Y2.5266	A[#<_a> +0.00137]
G1	X1.3175	Y2.4649	A[#<_a> +0.00137]
G1	X1.4369	Y2.3973	A[#<_a> +0.00137]
G1	X1.5528	Y2.3239	A[#<_a> +0.00137]
G1	X1.6649	Y2.2449	A[#<_a> +0.00137]
G1	X1.7731	Y2.1605	A[#<_a> +0.00137]
G1	X1.877	Y2.0709	A[#<_a> +0.00137]
G1	X1.9763	Y1.9763	A[#<_a> +0.00137]
G1	X2.0709	Y1.877	A[#<_a> +0.00137]
G1	X2.1605	Y1.7731	A[#<_a> +0.00137]
G1	X2.2449	Y1.6649	A[#<_a> +0.00137]
G1	X2.3239	Y1.5528	A[#<_a> +0.00137]
G1	X2.3973	Y1.4369	A[#<_a> +0.00137]
G1	X2.4649	Y1.3175	A[#<_a> +0.00137]
G1	X2.5266	Y1.195	A[#<_a> +0.00137]
G1	X2.5822	Y1.0696	A[#<_a> +0.00137]
G1	X2.6316	Y0.9416	A[#<_a> +0.00137]
G1	X2.6746	Y0.8113	A[#<_a> +0.00137]
G1	X2.7112	Y0.6791	A[#<_a> +0.00137]
G1	X2.7412	Y0.5453	A[#<_a> +0.00137]
G1	X2.7647	Y0.4101	A[#<_a> +0.00137]
G1	X2.7815	Y0.274	A[#<_a> +0.00137]
G1	X2.7916	Y0.1371	A[#<_a> +0.00137]
G1	X2.7949	Y0	A[#<_a> +0.00137]
G1	X2.7916	Y-0.1371	A[#<_a> +0.00137]
G1	X2.7815	Y-0.274	A[#<_a> +0.00137]
G1	X2.7647	Y-0.4101	A[#<_a> +0.00137]
G1	X2.7412	Y-0.5453	A[#<_a> +0.00137]
G1	X2.7112	Y-0.6791	A[#<_a> +0.00137]
G1	X2.6746	Y-0.8113	A[#<_a> +0.00137]
G1	X2.6316	Y-0.9416	A[#<_a> +0.00137]
G1	X2.5822	Y-1.0696	A[#<_a> +0.00137]
G1	X2.5266	Y-1.195	A[#<_a> +0.00137]
G1	X2.4649	Y-1.3175	A[#<_a> +0.00137]
G1	X2.3973	Y-1.4369	A[#<_a> +0.00137]
G1	X2.3239	Y-1.5528	A[#<_a> +0.00137]
G1	X2.2449	Y-1.6649	A[#<_a> +0.00137]
G1	X2.1605	Y-1.7731	A[#<_a> +0.00137]
G1	X2.0709	Y-1.877	A[#<_a> +0.00137]
G1	X1.9763	Y-1.9763	A[#<_a> +0.00137]
G0	X1.5	Y-1.8536	F1600
G1	X1.5	Y1.8536	A[#<_a> +0.03707]	F500
G1	X0.5	Y2.3312	A[#<_a> +0.01108]
G1	X0.5	Y-2.3312	A[#<_a> +0.04662]
G1	X-0.5	Y-2.3312	A[#<_a> +0.01]
G1	X-0.5	Y2.3312	A[#<_a> +0.04662]
G1	X-1.5	Y1.8536	A[#<_a> +0.01108]
G1	X-1.5	Y-1.8536	A[#<_a> +0.03707]

G1	Z[#<_z> +0.2]	F300

M99
%