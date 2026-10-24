use slot::{frontend::Frontend,audio::StubSink};
use slot_gfx::{Compositor,SdlSurface,Surface};
use slot_input::{Btn,InputSource,Millis,RawEvent};
use slot_power::DevicePlatform;
use slot_ui::QuickRow;
use std::{path::{Path,PathBuf},time::Duration};
struct Pad(Vec<RawEvent>);
impl InputSource for Pad { fn poll(&mut self,_:Millis)->Vec<RawEvent>{std::mem::take(&mut self.0)} }
fn frames(f:&mut Frontend,c:&mut Compositor,s:&mut SdlSurface,p:&mut Pad,t:&mut u64,n:usize){
 for _ in 0..n { *t+=20;f.advance_at(p,*t,0.02);f.render(c,(640,480));s.swap().unwrap();std::thread::sleep(Duration::from_millis(16)); }
}
fn press(f:&mut Frontend,c:&mut Compositor,s:&mut SdlSurface,p:&mut Pad,t:&mut u64,b:Btn){
 p.0.push(RawEvent::Down(b));frames(f,c,s,p,t,1);p.0.push(RawEvent::Up(b));frames(f,c,s,p,t,2);
}
fn capture(f:&mut Frontend,c:&mut Compositor,s:&mut SdlSurface,path:&Path){
 f.render(c,(640,480));
 let read:unsafe extern "C" fn(i32,i32,i32,i32,u32,u32,*mut std::ffi::c_void)=unsafe{std::mem::transmute(s.proc_address("glReadPixels"))};
 let mut pixels=vec![0u8;640*480*4];unsafe{read(0,0,640,480,0x1908,0x1401,pixels.as_mut_ptr().cast())};
 let rgba:Vec<u8>=pixels.chunks_exact(640*4).rev().flatten().copied().collect();
 assert!(rgba.chunks_exact(4).any(|p|p[0]>100&&p[1]>100&&p[2]>100),"empty/black menu");
 let mut e=png::Encoder::new(std::fs::File::create(path).unwrap(),640,480);e.set_color(png::ColorType::Rgba);e.set_depth(png::BitDepth::Eight);e.write_header().unwrap().write_image_data(&rgba).unwrap();
}
fn main(){
 let root=PathBuf::from(std::env::var("SLOT_ROOT").unwrap());let out=PathBuf::from(std::env::args().nth(1).unwrap());std::fs::create_dir_all(&out).unwrap();
 let mut s=SdlSurface::new().unwrap();assert_eq!(s.window_size(),(640,480));let mut c=Compositor::new(&s).unwrap();
 let mut f=Frontend::boot_with(Box::new(DevicePlatform::new(root)),Box::new(StubSink::draining()));f.upload_faces(&mut c);f.upload_bezel(&mut c,(640,480));
 let(mut p,mut t)=(Pad(vec![]),0);frames(&mut f,&mut c,&mut s,&mut p,&mut t,30);
 if std::env::args().nth(2).as_deref()==Some("--suspend") {
  let game_sleep=std::env::var("SLOT_TEST_SLEEP_GAME").as_deref()==Ok("1");
  if game_sleep {
   press(&mut f,&mut c,&mut s,&mut p,&mut t,Btn::A);
   frames(&mut f,&mut c,&mut s,&mut p,&mut t,240);
   assert!(matches!(f.app().phase(),slot::app::Phase::Playing{..}),"test game did not enter Playing before suspend");
  }
  let successes=||std::fs::read_to_string("/sys/power/suspend_stats/success").unwrap().trim().parse::<u64>().unwrap();let before=successes();
  press(&mut f,&mut c,&mut s,&mut p,&mut t,Btn::Power);
  assert!(matches!(f.app().phase(),slot::app::Phase::Doze{..}),"normal Power path did not pause/save before suspend");
  let elapsed=slot::rg353v_sleep::Sleeper::from_env().sleep(Some(Duration::from_secs(5))).expect("production suspend adapter did not suspend");
  assert!(elapsed>=Duration::from_secs(3)&&elapsed<Duration::from_secs(15));assert_eq!(successes(),before+1);
  f.account_suspend(elapsed);
  press(&mut f,&mut c,&mut s,&mut p,&mut t,Btn::Power);
  assert!(!matches!(f.app().phase(),slot::app::Phase::Doze{..}),"normal Power path did not wake");
  frames(&mut f,&mut c,&mut s,&mut p,&mut t,100);
  if game_sleep {assert!(matches!(f.app().phase(),slot::app::Phase::Playing{..}),"test game did not return to Playing after wake");}
  capture(&mut f,&mut c,&mut s,&out.join("after-suspend.png"));
  if game_sleep {println!("PASS game Playing -> normal Power Doze -> deep suspend -> Playing redraw");}
  println!("PASS production pause/save + timed suspend + Power wake and KMS/GLES redraw; suspend counter {} -> {}",before,successes());return;
 }
 for (index,row,name) in [(0,QuickRow::Screen,"screen"),(1,QuickRow::Game,"gameplay"),(2,QuickRow::General,"general"),(3,QuickRow::Network,"network"),(4,QuickRow::Updates,"updates"),(5,QuickRow::Diagnostics,"diagnostics"),(6,QuickRow::About,"about")] {
  // Start a fresh menu so navigation is independent of a previous subview.
  press(&mut f,&mut c,&mut s,&mut p,&mut t,Btn::Menu);
  assert_eq!(f.app().quick_menu(),Some(QuickRow::Screen));
  for _ in 0..index {press(&mut f,&mut c,&mut s,&mut p,&mut t,Btn::Down);}
  assert_eq!(f.app().quick_menu(),Some(row));
  if index==0 {capture(&mut f,&mut c,&mut s,&out.join("main.png"));}
  press(&mut f,&mut c,&mut s,&mut p,&mut t,Btn::A);frames(&mut f,&mut c,&mut s,&mut p,&mut t,100);
  capture(&mut f,&mut c,&mut s,&out.join(format!("{name}.png")));
  if name=="network" {assert!(f.app().network_open());println!("NETWORK {:?}",f.app().network_values());}
  if name=="diagnostics" {assert!(!f.app().diagnostics_view().is_empty());println!("DIAGNOSTICS {:?}",f.app().diagnostics_view());}
  println!("PASS menu {name}");
  press(&mut f,&mut c,&mut s,&mut p,&mut t,Btn::B);press(&mut f,&mut c,&mut s,&mut p,&mut t,Btn::B);
 }
}
