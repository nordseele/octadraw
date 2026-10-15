| SPDX-License-Identifier: MIT
| Copyright (c) 2026 nordseele (see LICENSE-MIT)
| OctaDraw ColdFire renderer: draws a command list on a 1-bit surface. a3 = surface {w,h,stride,bits,mask}.
| Commands: byte kind,x,row,operation; then rectangle x1,row1,0,0 or glyph pointer.
| Operation: 0 clear (white), 1 set (black), 2 invert. Kind255 ends the list.
| a2 = commands. Caller owns surface lifetime, redraw scheduling and navigation.
| Runtime entries (globals): ui_draw_text (text in a slot exported by OctaDraw), ui_draw_rect.
| No fixed address: assemble and link it into your module like any other code.
        .text
.Lui_commands:
        moveq   #0,%d5
        move.b  %a2@,%d5
        cmpi.l  #255,%d5
        beq.w   .Lui_commands_done
        moveq   #0,%d0
        moveq   #0,%d1
        moveq   #0,%d4
        move.b  %a2@(1),%d0
        move.b  %a2@(2),%d1
        move.b  %a2@(3),%d4
        tst.l   %d5
        bne.w   .Lui_command_glyph
        moveq   #0,%d2
        moveq   #0,%d3
        move.b  %a2@(4),%d2
        move.b  %a2@(5),%d3
        bsr.w   .Lui_rect
        bra.w   .Lui_command_next
.Lui_command_glyph:
        movea.l %a2@(4),%a0
        lea     .Lui_px(%pc),%a1                | static commands are clipped by the generator
        bsr.w   .Lui_gly
.Lui_command_next:
        addq.l  #8,%a2
        bra.w   .Lui_commands
.Lui_commands_done:
        rts

.Lui_px:
        lea     %sp@(-16),%sp
        moveml  %d6-%d7/%a0-%a1,%sp@
        move.l  %a3@(4),%d6
        subq.l  #1,%d6
        sub.l   %d1,%d6                         | y up = h - 1 - row
        moveq   #31,%d7
        and.l   %d6,%d7
        lsr.l   #5,%d6                          | column long index
        neg.l   %d7
        addi.l  #31,%d7                         | bit position
        move.l  %d7,%sp@-
        move.l  %a3@(8),%d7                     | stride
        mulu.l  %d0,%d7
        add.l   %d6,%d7
        lsl.l   #2,%d7
        movea.l %a3@(12),%a0                    | bits
        adda.l  %d7,%a0
        movea.l %a3@(16),%a1                    | mask
        adda.l  %d7,%a1
        move.l  %sp@+,%d7
        move.l  %a0@,%d6
        cmpi.l  #1,%d4
        beq.s   .Luip_set
        bhi.s   .Luip_flip
        bclr    %d7,%d6
        bra.s   .Luip_put
.Luip_set:
        bset    %d7,%d6
        bra.s   .Luip_put
.Luip_flip:
        bchg    %d7,%d6
.Luip_put:
        move.l  %d6,%a0@
        move.l  %a1@,%d6
        bset    %d7,%d6                         | mask bit always set (opaque)
        move.l  %d6,%a1@
        moveml  %sp@,%d6-%d7/%a0-%a1
        lea     %sp@(16),%sp
        rts

| .Lui_rect — a3 = surface; d0 x0, d1 row0, d2 x1, d3 row1, d4 op.
.Lui_rect:
        lea     %sp@(-16),%sp
        moveml  %d2-%d5,%sp@
        move.l  %d1,%d5
.Luir_x:
        cmp.l   %d2,%d0
        bgt.s   .Luir_out
        move.l  %d5,%d1
.Luir_r:
        cmp.l   %d3,%d1
        bgt.s   .Luir_nx
        bsr.w   .Lui_px
        addq.l  #1,%d1
        bra.s   .Luir_r
.Luir_nx:
        addq.l  #1,%d0
        bra.s   .Luir_x
.Luir_out:
        moveml  %sp@,%d2-%d5
        lea     %sp@(16),%sp
        rts

| .Lui_gly — a3 = surface; a0 = bitmap; d0 = x, d1 = row; a1 = pixel routine (.Lui_px or .Lui_pxc).
.Lui_gly:
        lea     %sp@(-32),%sp
        moveml  %d2-%d7/%a2,%sp@
        movea.l %a0,%a2
        move.l  %d0,%d2
        move.l  %d1,%d3
        clr.l   %d5
.Luig_r:
        moveq   #0,%d0
        move.b  %a2@(1),%d0
        cmp.l   %d0,%d5
        bcc.s   .Luig_out
        moveq   #0,%d6
        move.b  %a2@(2,%d5:l),%d6
        clr.l   %d7
.Luig_c:
        moveq   #0,%d0
        move.b  %a2@,%d0
        cmp.l   %d0,%d7
        bcc.s   .Luig_nr
        moveq   #7,%d1
        sub.l   %d7,%d1
        btst    %d1,%d6
        beq.s   .Luig_nc
        move.l  %d2,%d0
        add.l   %d7,%d0
        move.l  %d3,%d1
        add.l   %d5,%d1
        jsr     %a1@
.Luig_nc:
        addq.l  #1,%d7
        bra.s   .Luig_c
.Luig_nr:
        addq.l  #1,%d5
        bra.s   .Luig_r
.Luig_out:
        moveml  %sp@,%d2-%d7/%a2
        lea     %sp@(32),%sp
        rts

| ---- runtime text ---------------------------------------------------------------------------------------
| ui_draw_rect — a3 = surface; d0 x0, d1 row0, d2 x1, d3 row1 (inclusive, inside the surface); d4 op 0/1/2.
| Preserves d2-d7/a2-a6.
        .globl  ui_draw_rect
ui_draw_rect:
        bra.w   .Lui_rect

| ui_draw_text — a3 = surface; a0 = NUL-terminated ASCII string; a1 = slot (ui_slot_* from the export);
| d0 = flags: bit 0 draw the selection highlight, bit 1 fill the slot box with its background first.
| Same result as the editor's text layer: case, fit to the room, alignment, clip to the box.
| Returns d0 = ink width drawn. Preserves d2-d7/a2-a6.
| Slot: .long font; .byte box x0,row0,x1,row1; .byte left,right,top,align; .byte ink,bg,hp,sel_top;
|       .byte sel_h,space_adv,case,0
| Font: 95 entries for codes 32..126: .long glyph (0 = no ink); .byte advance,ink width,row,x offset
        .globl  ui_draw_text
ui_draw_text:
        lea     %sp@(-56),%sp
        moveml  %d2-%d7/%a2-%a6,%sp@
        movea.l %a0,%a2                         | string
        movea.l %a1,%a4                         | slot
        movea.l %a1@,%a5                        | font
        move.l  %d0,%d7                         | flags
        moveq   #0,%d2                          | characters kept
        moveq   #0,%d3                          | advances so far
        moveq   #0,%d4                          | ink width
        moveq   #0,%d5
        move.b  %a4@(9),%d5
        moveq   #0,%d0
        move.b  %a4@(8),%d0
        sub.l   %d0,%d5                         | room = right - left
.Luit_fit:
        moveq   #0,%d0
        move.b  %a2@(0,%d2:l),%d0
        beq.s   .Luit_fitted
        bsr.w   .Lui_entry
        moveq   #0,%d6
        move.b  %a0@(5),%d6
        add.l   %d3,%d6                         | width if this character is the last one
        cmp.l   %d5,%d6
        bgt.s   .Luit_fitted
        move.l  %d6,%d4
        add.l   %d1,%d3
        addq.l  #1,%d2
        bra.s   .Luit_fit
.Luit_fitted:
        move.l  %d2,%sp@(44)
        move.l  %d4,%sp@(48)
        moveq   #0,%d6
        move.b  %a4@(8),%d6                     | x = left
        moveq   #0,%d0
        move.b  %a4@(11),%d0                    | align: 0 start, 1 centre, 2 end
        beq.s   .Luit_x
        move.l  %d5,%d1
        sub.l   %d4,%d1
        cmpi.l  #1,%d0
        bne.s   .Luit_end
        lsr.l   #1,%d1
.Luit_end:
        add.l   %d1,%d6
.Luit_x:
        move.l  %d6,%sp@(52)
        btst    #1,%d7
        beq.s   .Luit_ink
        moveq   #0,%d4
        move.b  %a4@(13),%d4                    | background, 255 = none
        cmpi.l  #255,%d4
        beq.s   .Luit_ink
        bsr.w   .Lui_box
        bsr.w   .Lui_rect
.Luit_ink:
        move.l  %sp@(52),%d5                    | cursor
        moveq   #0,%d2
.Luit_char:
        cmp.l   %sp@(44),%d2
        bge.s   .Luit_drawn
        moveq   #0,%d0
        move.b  %a2@(0,%d2:l),%d0
        bsr.w   .Lui_entry
        move.l  %d1,%d3                         | advance
        move.l  %a0@,%d0
        beq.s   .Luit_next
        moveq   #0,%d0
        move.b  %a0@(7),%d0
        extb.l  %d0
        add.l   %d5,%d0                         | x = cursor + x offset
        moveq   #0,%d1
        move.b  %a0@(6),%d1
        moveq   #0,%d4
        move.b  %a4@(10),%d4
        add.l   %d4,%d1                         | row = top + glyph row
        moveq   #0,%d4
        move.b  %a4@(12),%d4                    | ink
        movea.l %a0@,%a0
        lea     .Lui_pxc(%pc),%a1
        bsr.w   .Lui_gly
.Luit_next:
        add.l   %d3,%d5
        addq.l  #1,%d2
        bra.s   .Luit_char
.Luit_drawn:
        btst    #0,%d7
        beq.w   .Luit_done
        move.l  %sp@(48),%d3
        beq.w   .Luit_done
        move.l  %sp@(52),%d6
        moveq   #0,%d4
        move.b  %a4@(14),%d4                    | highlight padding
        move.l  %d6,%d0
        sub.l   %d4,%d0                         | x0 = x - hp
        move.l  %d6,%d2
        add.l   %d3,%d2
        subq.l  #1,%d2
        add.l   %d4,%d2                         | x1 = x + width - 1 + hp
        moveq   #0,%d1
        move.b  %a4@(15),%d1
        move.l  %d1,%d3
        sub.l   %d4,%d1                         | row0 = sel_top - hp
        moveq   #0,%d5
        move.b  %a4@(16),%d5
        add.l   %d5,%d3
        subq.l  #1,%d3
        add.l   %d4,%d3                         | row1 = sel_top + sel_h - 1 + hp
        moveq   #0,%d5
        move.b  %a4@(4),%d5
        cmp.l   %d5,%d0
        bge.s   .Luis_x1
        move.l  %d5,%d0
.Luis_x1:
        move.b  %a4@(6),%d5
        cmp.l   %d5,%d2
        ble.s   .Luis_r0
        move.l  %d5,%d2
.Luis_r0:
        move.b  %a4@(5),%d5
        cmp.l   %d5,%d1
        bge.s   .Luis_r1
        move.l  %d5,%d1
.Luis_r1:
        move.b  %a4@(7),%d5
        cmp.l   %d5,%d3
        ble.s   .Luis_go
        move.l  %d5,%d3
.Luis_go:
        cmp.l   %d0,%d2
        blt.s   .Luit_done
        cmp.l   %d1,%d3
        blt.s   .Luit_done
        moveq   #2,%d4
        bsr.w   .Lui_rect
.Luit_done:
        move.l  %sp@(48),%d0
        moveml  %sp@,%d2-%d7/%a2-%a6
        lea     %sp@(56),%sp
        rts

| .Lui_entry — d0 = character, a4 = slot, a5 = font -> a0 = font entry, d1 = advance. Uses d0, d1, a0.
.Lui_entry:
        moveq   #0,%d1
        move.b  %a4@(18),%d1                    | case: 1 upper, 2 lower
        cmpi.l  #1,%d1
        bne.s   .Luie_lower
        cmpi.l  #97,%d0
        blt.s   .Luie_range
        cmpi.l  #122,%d0
        bgt.s   .Luie_range
        subi.l  #32,%d0
        bra.s   .Luie_range
.Luie_lower:
        cmpi.l  #2,%d1
        bne.s   .Luie_range
        cmpi.l  #65,%d0
        blt.s   .Luie_range
        cmpi.l  #90,%d0
        bgt.s   .Luie_range
        addi.l  #32,%d0
.Luie_range:
        cmpi.l  #32,%d0
        blt.s   .Luie_bad
        cmpi.l  #126,%d0
        ble.s   .Luie_ok
.Luie_bad:
        moveq   #63,%d0                         | outside the table: drawn as '?'
.Luie_ok:
        move.l  %d0,%d1
        subi.l  #32,%d1
        lsl.l   #3,%d1
        lea     %a5@(0,%d1:l),%a0
        moveq   #0,%d1
        move.b  %a0@(4),%d1
        cmpi.l  #32,%d0
        bne.s   .Luie_out
        move.b  %a4@(17),%d1                    | the slot's space advance
.Luie_out:
        rts

| .Lui_box — a4 = slot -> d0 x0, d1 row0, d2 x1, d3 row1.
.Lui_box:
        moveq   #0,%d0
        move.b  %a4@(4),%d0
        moveq   #0,%d1
        move.b  %a4@(5),%d1
        moveq   #0,%d2
        move.b  %a4@(6),%d2
        moveq   #0,%d3
        move.b  %a4@(7),%d3
        rts

| .Lui_pxc — .Lui_px clipped to the slot box (a4).
.Lui_pxc:
        move.l  %d2,%sp@-
        moveq   #0,%d2
        move.b  %a4@(4),%d2
        cmp.l   %d2,%d0
        blt.s   .Luipc_out
        move.b  %a4@(6),%d2
        cmp.l   %d2,%d0
        bgt.s   .Luipc_out
        move.b  %a4@(5),%d2
        cmp.l   %d2,%d1
        blt.s   .Luipc_out
        move.b  %a4@(7),%d2
        cmp.l   %d2,%d1
        bgt.s   .Luipc_out
        bsr.w   .Lui_px
.Luipc_out:
        move.l  %sp@+,%d2
        rts
