#!/usr/bin/env python3
"""Exercise package dependency removal, restoration and actual build-result guards."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT/'ports/rg353v/rocknix/slot-startup-profile'
spec = importlib.util.spec_from_file_location('userspace',PKG/'tools/configure-userspace.py')
m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
POLICY = json.loads((PKG/'config/userspace-lean-v1.json').read_text())


class Userspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        options = self.root/'projects/ROCKNIX/options'
        options.parent.mkdir(parents=True)
        options.write_text('SQUASHFS_COMPRESSION="zstd"\n')
        self.sources = self.root/'projects/ROCKNIX/packages/graphics'
        self.device = self.root/'projects/ROCKNIX/devices/RK3566/packages'
        (self.device/'slot-rg353v').mkdir(parents=True)
        (self.device/'slot-rg353v/package.mk').write_text('PKG_DEPENDS_TARGET="toolchain SDL2 alsa pipewire wireplumber samba"\n')
        self.original = {
            'SDL2': 'PKG_NAME="SDL2"\nPKG_DEPENDS_TARGET="toolchain alsa-lib libdrm libmali pulseaudio wayland swaywm-env librga vulkan-loader"\npre_configure_target(){\n PKG_CMAKE_OPTS_TARGET+=" -DSDL_WAYLAND=ON -DSDL_PULSEAUDIO=ON"\n}\n',
            'SDL2_glesonly': '. "$(get_pkg_directory SDL2)/package.mk"\nPKG_NAME="SDL2_glesonly"\n',
            'libmali': 'PKG_NAME="libmali"\nPKG_DEPENDS_TARGET="toolchain libdrm vulkan-tools vulkan-wsi-layer"\npost_makeinstall_target() {\n  mv "${INSTALL}"/usr/lib/mali/libMaliVulkan.* "${INSTALL}"/usr/lib/\n}\n',

        }
        policy = json.loads(json.dumps(POLICY))
        for name,text in self.original.items():
            folder = self.sources/name;folder.mkdir(parents=True)
            (folder/'package.mk').write_text(text)
            policy['source_sha256'][name] = m.hashlib.sha256(text.encode()).hexdigest()
        (self.sources/'SDL2/patches').mkdir()
        (self.sources/'SDL2/patches/fix.patch').write_text('preserve upstream fixes')
        (self.sources/'SDL2_glesonly/patches').symlink_to('../SDL2/patches')
        self.writer=self.root/'projects/ROCKNIX/packages/sysutils/squashfs-tools/package.mk'
        self.writer.parent.mkdir(parents=True)
        self.writer_original='PKG_DEPENDS_HOST="zstd:host"\nPKG_NEED_UNPACK="zstd"\nmake_host() {\n  make mksquashfs LZ4_SUPPORT=0\n}\n'
        self.writer.write_text(self.writer_original)
        policy['source_sha256']['squashfs-tools']=m.hashlib.sha256(self.writer_original.encode()).hexdigest()
        self.policy = self.root/'policy.json';self.policy.write_text(json.dumps(policy))

    def stage(self,profile=m.PROFILE):
        return m.stage(self.root,self.policy,profile)

    def test_small_image_blocks_are_scoped_idempotent_and_reversible(self):
        options=self.root/'projects/ROCKNIX/options';original=options.read_text()
        self.stage();first=options.read_text();self.stage();self.assertEqual(options.read_text(),first)
        def value(base,device,arch):
            return subprocess.run(['bash','-c','source "$1"; printf "%s|%s" "$SQUASHFS_COMPRESSION" "${SQUASHFS_COMPRESSION_OPTION:-upstream}"','test',str(options)],
                                  env=dict(os.environ,BASE_ONLY=base,DEVICE=device,ARCH=arch),capture_output=True,text=True,check=True).stdout
        self.assertEqual(value('true','RK3566','aarch64'),'lz4|-Xhc -b 65536')
        for args in [('false','RK3566','aarch64'),('true','other','aarch64'),('true','RK3566','arm')]:
            self.assertEqual(value(*args),'zstd|upstream')
        self.stage(None);self.assertEqual(options.read_text(),original)
        options.write_text(original+'SQUASHFS_COMPRESSION_OPTION="custom"\n')
        with self.assertRaisesRegex(ValueError,'SquashFS options'):self.stage()

    def test_host_writer_has_lz4_without_changing_target_recipe_and_restores_baseline(self):
        self.stage()
        script='get_pkg_directory() { echo /source/lz4; }; make() { printf "%s" "$*"; }; source "$1"; printf "%s\\n" "$PKG_DEPENDS_HOST"; make_host'
        result=subprocess.run(['bash','-c',script,'test',str(self.writer)],capture_output=True,text=True,check=True).stdout
        self.assertIn('lz4:host',result);self.assertIn('LZ4_SUPPORT=1',result)
        first=self.writer.read_text();self.stage();self.assertEqual(first,self.writer.read_text())
        self.stage(None);self.assertEqual(self.writer.read_text(),self.writer_original)
        self.writer.write_text(self.writer_original+'changed')
        with self.assertRaisesRegex(ValueError,'upstream recipe: squashfs-tools'):self.stage()

    def run_recipe(self,name):
        script = 'get_pkg_directory() { printf "%s/SDL2" "$PROJECT_PACKAGES"; }; source "$1"; pre_configure_target; printf "%s\\n%s" "$PKG_DEPENDS_TARGET" "$PKG_CMAKE_OPTS_TARGET"'
        return subprocess.run(['bash','-c',script,'test',str(self.sources/name/'package.mk')],env=dict(os.environ,PROJECT_PACKAGES=str(self.sources)),capture_output=True,text=True,check=True).stdout.splitlines()

    def test_both_sdl_variants_keep_kms_audio_input_and_original_patches(self):
        self.stage()
        for name in ('SDL2', 'SDL2_glesonly'):
            deps,flags = self.run_recipe(name)
            self.assertEqual(deps.split(),['toolchain','alsa-lib','libdrm','libmali'])
            for key,value in POLICY['sdl_required'].items():
                values=[part.split('=',1)[1] for part in flags.split() if part.startswith('-D'+key+'=')]
                self.assertEqual(values[-1],value,key)
            self.assertEqual((self.sources/name/'patches/fix.patch').read_text(),'preserve upstream fixes')
            self.assertFalse((self.device/name).exists())

    def test_gles_recipe_preserves_install_hook_without_requiring_vulkan_files(self):
        policy = json.loads(self.policy.read_text())
        policy['mali_variant'] = 'bifrost-g52-g29p1-gles'
        self.policy.write_text(json.dumps(policy))
        self.stage()
        recipe = self.sources/'libmali/package.mk'
        first = recipe.read_text()
        self.stage()
        self.assertEqual(recipe.read_text(), first)
        install = self.root/'mali-install'
        (install/'usr/lib/mali').mkdir(parents=True)
        script = 'set -e; source "$1"; post_makeinstall_target; printf "%s\\n%s\\n%s" "$PLATFORM" "$PKG_DEPENDS_TARGET" "$PKG_MESON_OPTS_TARGET"'
        result = subprocess.run(['bash', '-c', script, 'test', str(recipe)],
                                env=dict(os.environ, INSTALL=str(install)),
                                capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertEqual(result[0], '-gles')
        self.assertEqual(result[1].split(), ['toolchain', 'libdrm'])
        self.assertEqual(result[2].split()[-1], '-Dplatform=gles')
        self.stage(None)
        self.assertEqual(recipe.read_text(), self.original['libmali'])

    def test_full_variant_keeps_original_graphics_and_unknown_variant_is_rejected(self):
        policy = json.loads(self.policy.read_text())
        policy['mali_variant'] = 'bifrost-g52-g29p1-full'
        self.policy.write_text(json.dumps(policy))
        self.stage()
        recipe = self.sources/'libmali/package.mk'
        self.assertEqual(recipe.read_text(), self.original['libmali'])
        policy = json.loads(self.policy.read_text())
        policy['mali_variant'] = 'unknown'
        self.policy.write_text(json.dumps(policy))
        with self.assertRaisesRegex(ValueError, 'Unknown Mali'):
            self.stage()

    def test_trial_removes_audio_servers_and_baseline_restores_them(self):
        self.stage()
        recipe=self.device/'slot-rg353v/package.mk'
        def deps():
            return subprocess.run(['bash','-c','source "$1"; echo "$PKG_DEPENDS_TARGET"','test',str(recipe)],capture_output=True,text=True,check=True).stdout.split()
        self.assertNotIn('pipewire',deps());self.assertIn('alsa',deps())
        self.stage(None)
        self.assertIn('pipewire',deps());self.assertIn('wireplumber',deps())
        self.assertEqual((self.sources/'SDL2/package.mk').read_text(),self.original['SDL2'])

    def test_unknown_profile_changed_recipe_and_existing_override_are_rejected(self):
        with self.assertRaises(ValueError):self.stage('unknown')
        recipe=self.sources/'SDL2/package.mk';original=recipe.read_text();recipe.write_text(original+'changed')
        with self.assertRaisesRegex(ValueError,'changed upstream'):self.stage()
        recipe.write_text(original)
        (self.device/'SDL2').mkdir()
        (self.device/'SDL2/package.mk').write_text('manual device override')
        with self.assertRaisesRegex(ValueError,'device override'):self.stage()

    def built(self):
        build=self.root/'build.ROCKNIX-RK3566.aarch64'
        for name in POLICY['retain']:(build/'image/.stamps'/name).mkdir(parents=True)
        for name in ('SDL2', 'SDL2_glesonly'):
            cache=build/'build'/(name+'-2.32.10')/'.aarch64-test/CMakeCache.txt'
            cache.parent.mkdir(parents=True);cache.write_text(''.join(k+':BOOL='+v+'\n' for k,v in POLICY['sdl_required'].items()))
            header=cache.parent/'include-config-release/SDL2/SDL_config.h';header.parent.mkdir(parents=True)
            header.write_text(''.join('#define '+n+' 1\n' for n in ('SDL_AUDIO_DRIVER_ALSA','SDL_VIDEO_DRIVER_KMSDRM','SDL_VIDEO_OPENGL_ES2','SDL_JOYSTICK_LINUX')))
        return build

    def test_validation_rejects_reintroduced_compositor_and_lost_wifi(self):
        build=self.built();m.validate(self.root,self.policy)
        unwanted=build/'image/.stamps/sway';unwanted.mkdir()
        with self.assertRaisesRegex(ValueError,'unwanted'):m.validate(self.root,self.policy)
        unwanted.rmdir();(build/'image/.stamps/networkmanager').rmdir()
        with self.assertRaisesRegex(ValueError,'missing'):m.validate(self.root,self.policy)

    def test_validation_requires_real_kms_alsa_and_joystick_build_options(self):
        build=self.built()
        cache=next((build/'build/SDL2-2.32.10').rglob('CMakeCache.txt'));original=cache.read_text()
        for name in ('SDL_KMSDRM','SDL_ALSA','SDL_JOYSTICK','SDL_OPENGLES'):
            cache.write_text(original.replace(name+':BOOL=ON',name+':BOOL=OFF'))
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'expected ON'):m.validate(self.root,self.policy)
        cache.write_text(original)
        m.validate(self.root,self.policy)

    def test_cmake_internal_off_values_are_valid_but_compiled_wayland_is_not(self):
        build=self.built();cache=next((build/'build/SDL2-2.32.10').rglob('CMakeCache.txt'))
        cache.write_text(cache.read_text().replace('SDL_WAYLAND_SHARED:BOOL=OFF','SDL_WAYLAND_SHARED:INTERNAL=OFF'))
        m.validate(self.root,self.policy)
        header=cache.parent/'include-config-release/SDL2/SDL_config.h';header.write_text(header.read_text()+'#define SDL_VIDEO_DRIVER_WAYLAND 1\n')
        with self.assertRaisesRegex(ValueError,'compiled backend'):m.validate(self.root,self.policy)

    def test_compiled_sdl_must_not_repeat_slots_udev_input_scan(self):
        build=self.built()
        m.validate(self.root,self.policy)
        header=next((build/'build/SDL2-2.32.10').rglob('SDL_config.h'))
        header.write_text(header.read_text()+'#define SDL_USE_LIBUDEV 1\n')
        with self.assertRaisesRegex(ValueError,'compiled backend'):m.validate(self.root,self.policy)

    def image(self):
        root=self.root/'image'
        profile=root/'usr/share/slot/os-profile.json';profile.parent.mkdir(parents=True)
        profile.write_text(json.dumps({'userspace_profile':m.PROFILE}))
        for name in POLICY['image_remove_files']:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'unused payload')
        return root

    def test_prune_is_opt_in_and_preserves_removal_evidence_on_repeat(self):
        root=self.image();m.prune(root,self.policy)
        report=root/'usr/share/slot/hardware/userspace-trim.json';before=report.read_bytes()
        self.assertEqual(len(json.loads(before)['removed']),len(POLICY['image_remove_files']))
        m.prune(root,self.policy);self.assertEqual(report.read_bytes(),before)
        root2=self.root/'baseline';(root2/'usr/share/slot').mkdir(parents=True)
        (root2/'usr/share/slot/os-profile.json').write_text('{}')
        self.assertEqual(m.prune(root2,self.policy)['removed'],[])

    def test_prune_rejects_enabled_icd_or_symlink_before_any_deletion(self):
        root=self.image();icd=root/'usr/share/vulkan/icd.d/panfrost.json';icd.parent.mkdir(parents=True)
        icd.write_text('{"library_path":"libvulkan_panfrost.so"}')
        with self.assertRaisesRegex(ValueError,'ICD'):m.prune(root,self.policy)
        icd.unlink();first=root/POLICY['image_remove_files'][0];first.unlink();first.symlink_to('/dev/null')
        with self.assertRaisesRegex(ValueError,'symlink'):m.prune(root,self.policy)
        self.assertTrue((root/POLICY['image_remove_files'][1]).exists())


if __name__=='__main__':unittest.main()
