| SPDX-License-Identifier: MIT
| Copyright (c) 2026 nordseele (see LICENSE-MIT)
| List demo host code: the static frame from OctaDraw, then the live strings in its runtime slots.
| Link with the ui_generated.S exported from examples/demo/project.json.
|
| demo_list_draw — a3 = 128x64 surface; a0 = state:
|   .long title, selected row (0..3, anything else = none), name1..name4, value1..value4 (NUL-terminated ASCII)
| Preserves d2-d7/a2-a6.
        .text
        .globl  demo_list_draw
demo_list_draw:
        lea     %sp@(-16),%sp
        moveml  %d2-%d3/%a2/%a4,%sp@
        movea.l %a0,%a2                         | state
        jsr     ui_page_1                       | static layers: title bar, frame
        movea.l %a2@,%a0
        lea     ui_slot_1_title,%a1
        moveq   #2,%d0                          | fill the slot box first
        jsr     ui_draw_text
        lea     .Ldemo_rows(%pc),%a4
        moveq   #0,%d2                          | row
.Ldemo_row:
        moveq   #2,%d0
        cmp.l   %a2@(4),%d2
        bne.s   .Ldemo_name
        moveq   #3,%d0                          | the selected row: fill + highlight
.Ldemo_name:
        move.l  %d2,%d3
        lsl.l   #2,%d3
        movea.l %a2@(8,%d3:l),%a0               | name
        movea.l %a4@(0,%d3:l),%a1
        jsr     ui_draw_text
        movea.l %a2@(24,%d3:l),%a0              | value
        movea.l %a4@(16,%d3:l),%a1
        moveq   #2,%d0
        jsr     ui_draw_text
        addq.l  #1,%d2
        moveq   #4,%d0
        cmp.l   %d0,%d2
        blt.s   .Ldemo_row
        moveml  %sp@,%d2-%d3/%a2/%a4
        lea     %sp@(16),%sp
        rts

        .balign 4
.Ldemo_rows:
        .long   ui_slot_1_name1, ui_slot_1_name2, ui_slot_1_name3, ui_slot_1_name4
        .long   ui_slot_1_value1, ui_slot_1_value2, ui_slot_1_value3, ui_slot_1_value4
