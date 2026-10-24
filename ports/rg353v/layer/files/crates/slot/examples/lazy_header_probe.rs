use slot_store::{Cart, Platform};
use slot_ui::Shelf;
use std::path::PathBuf;
fn main() {
    let carts: Vec<Cart> = (0..64)
        .map(|i| Cart {
            platform: if i < 32 { Platform::Gb } else { Platform::Gbc },
            stem: format!("Cart{i:02}"),
            rom: PathBuf::from(format!("/tmp/slot-header-audit/Cart{i:02}.gb")),
            label: None,
            title: String::new(),
            code: String::new(),
            shell: None,
        })
        .collect();
    eprintln!("STAGE create");
    let mut shelf = Shelf::new(carts.clone());
    eprintln!("STAGE restock");
    shelf.restock(carts);
    eprintln!("STAGE done");
}
