pub const GBA_CART_W: u32 = 360;
pub const GBA_CART_H: u32 = 212;
pub const GB_CART_W: u32 = 312;
pub const GB_CART_H: u32 = 337;
pub const BOARD_W: u32 = GBA_CART_W;
pub const BOARD_H: u32 = GBA_CART_H;
pub const SOCKET_W: u32 = 64;
pub const SOCKET_H: u32 = 46;
pub const CHIP_W: u32 = 59;
pub const CHIP_H: u32 = 41;
pub const SLOT_W: u32 = 720;
pub const SLOT_H: u32 = 58;
pub const PORT_W: u32 = 720;
pub const PORT_H: u32 = SLOT_H;
pub const PLUG_W: u32 = 92;
pub const PLUG_H: u32 = 244;
pub const ADAPTER_W: u32 = 290;
pub const ADAPTER_H: u32 = 180;
pub const STICKER_W: u32 = 660;
pub const STICKER_H: u32 = 228;

pub(crate) struct Template {
    pub name: &'static str,
    pub bytes: &'static [u8],
    pub w: u32,
    pub h: u32,
}
pub(crate) const GBA_CART_PNG: Template = Template {
    name: "GBA_CART_PNG",
    bytes: include_bytes!("../../../assets/gba_cart.png"),
    w: GBA_CART_W,
    h: GBA_CART_H,
};
pub(crate) const GB_CART_PNG: Template = Template {
    name: "GB_CART_PNG",
    bytes: include_bytes!("../../../assets/gb_cart.png"),
    w: GB_CART_W,
    h: GB_CART_H,
};
pub(crate) const GBC_CART_PNG: Template = Template {
    name: "GBC_CART_PNG",
    bytes: include_bytes!("../../../assets/gbc_cart.png"),
    w: GB_CART_W,
    h: GB_CART_H,
};
pub(crate) const GBA_INTERIOR_PNG: Template = Template {
    name: "GBA_INTERIOR_PNG",
    bytes: include_bytes!("../../../assets/gba_interior.png"),
    w: BOARD_W,
    h: BOARD_H,
};
pub(crate) const GB_INTERIOR_PNG: Template = Template {
    name: "GB_INTERIOR_PNG",
    bytes: include_bytes!("../../../assets/gb_interior.png"),
    w: GB_CART_W,
    h: GB_CART_H,
};
pub(crate) const GBC_INTERIOR_PNG: Template = Template {
    name: "GBC_INTERIOR_PNG",
    bytes: include_bytes!("../../../assets/gbc_interior.png"),
    w: GB_CART_W,
    h: GB_CART_H,
};
pub(crate) const GB_BOARD_PNG: Template = Template {
    name: "GB_BOARD_PNG",
    bytes: include_bytes!("../../../assets/gb_board.png"),
    w: GB_CART_W,
    h: GB_CART_H,
};
pub(crate) const BOARD_PNG: Template = Template {
    name: "BOARD_PNG",
    bytes: include_bytes!("../../../assets/board.png"),
    w: BOARD_W,
    h: BOARD_H,
};
pub(crate) const SOCKET_PNG: Template = Template {
    name: "SOCKET_PNG",
    bytes: include_bytes!("../../../assets/socket.png"),
    w: SOCKET_W,
    h: SOCKET_H,
};
pub(crate) const CHIP_PNG: Template = Template {
    name: "CHIP_PNG",
    bytes: include_bytes!("../../../assets/chip.png"),
    w: CHIP_W,
    h: CHIP_H,
};
pub(crate) const SLOT_BACK_DARK_PNG: Template = Template {
    name: "SLOT_BACK_DARK_PNG",
    bytes: include_bytes!("../../../assets/slot_back_dark.png"),
    w: SLOT_W,
    h: SLOT_H,
};
pub(crate) const SLOT_BACK_LIGHT_PNG: Template = Template {
    name: "SLOT_BACK_LIGHT_PNG",
    bytes: include_bytes!("../../../assets/slot_back_light.png"),
    w: SLOT_W,
    h: SLOT_H,
};
pub(crate) const SLOT_FRONT_DARK_PNG: Template = Template {
    name: "SLOT_FRONT_DARK_PNG",
    bytes: include_bytes!("../../../assets/slot_front_dark.png"),
    w: SLOT_W,
    h: SLOT_H,
};
pub(crate) const SLOT_FRONT_LIGHT_PNG: Template = Template {
    name: "SLOT_FRONT_LIGHT_PNG",
    bytes: include_bytes!("../../../assets/slot_front_light.png"),
    w: SLOT_W,
    h: SLOT_H,
};
pub(crate) const PORT_DARK_PNG: Template = Template {
    name: "PORT_DARK_PNG",
    bytes: include_bytes!("../../../assets/link_port_dark.png"),
    w: PORT_W,
    h: PORT_H,
};
pub(crate) const PORT_LIGHT_PNG: Template = Template {
    name: "PORT_LIGHT_PNG",
    bytes: include_bytes!("../../../assets/link_port_light.png"),
    w: PORT_W,
    h: PORT_H,
};
pub(crate) const PLUG_HOST_PNG: Template = Template {
    name: "PLUG_HOST_PNG",
    bytes: include_bytes!("../../../assets/link_plug_host.png"),
    w: PLUG_W,
    h: PLUG_H,
};
pub(crate) const PLUG_JOIN_PNG: Template = Template {
    name: "PLUG_JOIN_PNG",
    bytes: include_bytes!("../../../assets/link_plug_join.png"),
    w: PLUG_W,
    h: PLUG_H,
};
pub(crate) const ADAPTER_PNG: Template = Template {
    name: "ADAPTER_PNG",
    bytes: include_bytes!("../../../assets/link_adapter.png"),
    w: ADAPTER_W,
    h: ADAPTER_H,
};
pub(crate) const STICKER_PNG: Template = Template {
    name: "STICKER_PNG",
    bytes: include_bytes!("../../../assets/sticker.png"),
    w: STICKER_W,
    h: STICKER_H,
};
pub(crate) const GBA_SHELL_PNG: Template = Template {
    name: "GBA_SHELL_PNG",
    bytes: include_bytes!("../../../assets/gba_neutral.png"),
    w: GBA_CART_W,
    h: GBA_CART_H,
};
pub(crate) const GB_SHELL_PNG: Template = Template {
    name: "GB_SHELL_PNG",
    bytes: include_bytes!("../../../assets/gb_neutral.png"),
    w: GB_CART_W,
    h: GB_CART_H,
};
pub(crate) const GBC_SHELL_PNG: Template = Template {
    name: "GBC_SHELL_PNG",
    bytes: include_bytes!("../../../assets/gbc_neutral.png"),
    w: GB_CART_W,
    h: GB_CART_H,
};
pub(crate) const GBA_CLEAR_PNG: Template = Template {
    name: "GBA_CLEAR_PNG",
    bytes: include_bytes!("../../../assets/gba_clear.png"),
    w: GBA_CART_W,
    h: GBA_CART_H,
};
pub(crate) const GB_CLEAR_PNG: Template = Template {
    name: "GB_CLEAR_PNG",
    bytes: include_bytes!("../../../assets/gb_neutral.png"),
    w: GB_CART_W,
    h: GB_CART_H,
};
pub(crate) const GBC_CLEAR_PNG: Template = Template {
    name: "GBC_CLEAR_PNG",
    bytes: include_bytes!("../../../assets/gbc_clear.png"),
    w: GB_CART_W,
    h: GB_CART_H,
};
pub(crate) const ALL: &[Template] = &[
    GBA_CART_PNG,
    GB_CART_PNG,
    GBC_CART_PNG,
    GBA_INTERIOR_PNG,
    GB_INTERIOR_PNG,
    GBC_INTERIOR_PNG,
    GB_BOARD_PNG,
    BOARD_PNG,
    SOCKET_PNG,
    CHIP_PNG,
    SLOT_BACK_DARK_PNG,
    SLOT_BACK_LIGHT_PNG,
    SLOT_FRONT_DARK_PNG,
    SLOT_FRONT_LIGHT_PNG,
    PORT_DARK_PNG,
    PORT_LIGHT_PNG,
    PLUG_HOST_PNG,
    PLUG_JOIN_PNG,
    ADAPTER_PNG,
    STICKER_PNG,
    GBA_SHELL_PNG,
    GB_SHELL_PNG,
    GBC_SHELL_PNG,
    GBA_CLEAR_PNG,
    GB_CLEAR_PNG,
    GBC_CLEAR_PNG,
];
