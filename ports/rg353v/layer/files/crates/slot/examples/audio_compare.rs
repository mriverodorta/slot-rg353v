//! Silent DSP qualification. Host timings are not RG353V power measurements.
use slot::resample::Resampler;
use std::{hint::black_box, time::Instant};
const SRC: f64 = 32768.0;
const FPS: f64 = 59.7275;
fn tone(hz: f64, frames: usize) -> Vec<i16> {
    (0..frames)
        .flat_map(|i| {
            let v = (12000.0 * (std::f64::consts::TAU * hz * i as f64 / SRC).sin()).round() as i16;
            [v, v]
        })
        .collect()
}
fn rms(data: &[i16]) -> f64 {
    (data
        .iter()
        .step_by(2)
        .map(|&v| f64::from(v).powi(2))
        .sum::<f64>()
        / (data.len() / 2) as f64)
        .sqrt()
}
fn gain(hz: f64, rate: f64) -> f64 {
    let input = tone(hz, 32768);
    let mut r = Resampler::new(SRC, rate);
    let mut all = Vec::new();
    let mut output = Vec::new();
    for c in input.chunks(2 * 549) {
        r.process(c, &mut output);
        all.extend_from_slice(&output);
    }
    20.0 * (rms(&all[2048..all.len() - 2048]) / rms(&input)).log10()
}
fn main() {
    let input = tone(440.0, 549);
    let mut output = Vec::with_capacity(2000);
    println!("{{\"scope\":\"silent DSP only; host CPU; no ALSA or battery measurement\",\"source_hz\":32768,\"trials\":5,\"phases\":[");
    for (index, (name, rate)) in [("standard", 32768.0), ("enhanced", 48000.0)]
        .into_iter()
        .enumerate()
    {
        let mut r = Resampler::new(SRC, rate);
        for _ in 0..120 {
            r.process(&input, &mut output);
        }
        let mut times = Vec::new();
        for _ in 0..5 {
            let begin = Instant::now();
            for _ in 0..3600 {
                r.process(black_box(&input), &mut output);
                black_box(&output);
            }
            times.push(begin.elapsed().as_secs_f64() / 3600.0);
        }
        times.sort_by(f64::total_cmp);
        let gains = [440.0, 4000.0, 12000.0].map(|hz| gain(hz, rate));
        assert!(
            gains.iter().all(|v| v.is_finite() && v.abs() < 0.5),
            "passband gain changed: {gains:?}"
        );
        println!("{}{{\"mode\":\"{}\",\"output_hz\":{},\"median_us_per_game_frame\":{:.6},\"median_single_cpu_pct_at_gba_rate\":{:.6},\"gain_db_440_4000_12000\":[{:.6},{:.6},{:.6}]}}",if index==0{""}else{","},name,rate,times[2]*1e6,times[2]*FPS*100.0,gains[0],gains[1],gains[2]);
    }
    println!("]}}");
}
