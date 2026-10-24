#!/usr/bin/env python3
"""Native boot policy, device protections, real exFAT probes and readonly mount flow."""
import os,shlex,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'ports/rg353v/rocknix/slot-startup-profile/src/slot-sd-library-boot.c'
TEST=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <blkid/blkid.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/mount.h>
#include <sys/sysmacros.h>
#include <unistd.h>
static const char *image,*blank;
static unsigned mounts_count,unmounts_count;static unsigned long flags;
static bool games=true;
static int fake_lstat(const char *p,struct stat *s) {
 if(!strncmp(p,"/dev/mmcblk",11)){memset(s,0,sizeof *s);s->st_mode=S_IFBLK|0600;s->st_rdev=makedev(179,strstr(p,"p1")?289:288);return 0;}
 int rc=lstat(p,s);if(!rc&&!strcmp(p,"policy"))s->st_uid=0;return rc;
}
static char *fake_realpath(const char *p,char *s) {
 if(!strncmp(p,"/dev/mmcblk",11)){strcpy(s,p);return s;}return realpath(p,s);
}
static blkid_probe fake_probe(const char *p) {
 return blkid_new_probe_from_filename(!strncmp(p,"/dev/mmcblk",11)?(strstr(p,"p1")?image:blank):p);
}
static int fake_mount(const char *s,const char *t,const char *type,unsigned long fl,const void *data) {
 (void)s;(void)data;assert(!strcmp(type,"exfat"));flags=fl;mounts_count++;
 if(games){char p[PATH_MAX];assert(snprintf(p,sizeof p,"%s/Games",t)<(int)sizeof p);assert(!mkdir(p,0755));}return 0;
}
static int fake_umount(const char *p) {(void)p;unmounts_count++;return 0;}
#define lstat fake_lstat
#define realpath fake_realpath
#define blkid_new_probe_from_filename fake_probe
#define mount fake_mount
#define umount fake_umount
#define main production_main
#include "slot-sd-library-boot.c"
#undef main
#undef lstat
#undef realpath
#undef blkid_new_probe_from_filename
#undef mount
#undef umount
static void write_file(const char *p,const char *s) {FILE *f=fopen(p,"w");assert(f);assert(fputs(s,f)>=0);assert(!fclose(f));}
int main(int argc,char **argv) {
 assert(argc==5);image=argv[1];blank=argv[2];const char *uuid=argv[3];
 assert(disk_name("mmcblk12"));assert(!disk_name("mmcblk12p1"));assert(!disk_name("mmcblkA"));
 assert(same_disk("/dev/mmcblk12p3","/dev/mmcblk12"));assert(!same_disk("/dev/mmcblk123p1","/dev/mmcblk12"));
 assert(!same_disk("/dev/mmcblk12p3x","/dev/mmcblk12"));
 assert(filesystem(image,uuid));assert(!filesystem(blank,NULL));assert(!filesystem(image,"0000-0000"));
 assert(!filesystem(argv[4],NULL));assert(!filesystem("/does/not/exist",NULL));
 char tmp[]="/tmp/slot-sd-native-XXXXXX";assert(mkdtemp(tmp));assert(!chdir(tmp));
 assert(!mkdir("sys",0755));assert(!mkdir("fe2b0000.mmc",0755));
 assert(!mkdir("fe2b0000.mmc/mmcblk9",0755));assert(!mkdir("fe2b0000.mmc/mmcblk9/device",0755));
 assert(!mkdir("fe2b0000.mmc/mmcblk9/mmcblk9p1",0755));
 write_file("fe2b0000.mmc/mmcblk9/device/type","SD\n");
 write_file("fe2b0000.mmc/mmcblk9/device/cid","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n");
 write_file("fe2b0000.mmc/mmcblk9/device/serial","0x1234\n");
 write_file("fe2b0000.mmc/mmcblk9/dev","179:288\n");
 write_file("fe2b0000.mmc/mmcblk9/mmcblk9p1/dev","179:289\n");
 assert(!symlink("../fe2b0000.mmc/mmcblk9","sys/mmcblk9"));
 assert(!mkdir("run",0755));assert(!mkdir("run/TF1",0755));assert(!mkdir("run/TF2",0755));
 sysblocks="sys";mountfile="mounts";base="run";
 write_file(mountfile,"/dev/mmcblk0p1 /flash vfat ro 0 0\n/dev/mmcblk0p2 /storage ext4 rw 0 0\n");
 struct card c={0};assert(find_card(0,&c,true));assert(!find_card(1,&c,true));
 write_file(mountfile,"/dev/mmcblk9p1 /flash vfat ro 0 0\n/dev/mmcblk9p2 /storage ext4 rw 0 0\n");assert(!find_card(0,&c,true));
 write_file(mountfile,"/dev/mmcblk0p1 /flash vfat ro 0 0\n/dev/mmcblk0p2 /storage ext4 rw 0 0\n/dev/mmcblk9p1 /storage/slotcontent exfat rw 0 0\n");assert(!find_card(0,&c,true));
 write_file(mountfile,"/dev/mmcblk0p1 /flash vfat ro 0 0\n/dev/mmcblk0p2 /storage ext4 rw 0 0\n");
 assert(find_card(0,&c,true));c.state="No exFAT Games folder";
 assert(discover(&c,"run/TF1"));assert(mounts_count==1&&unmounts_count==0);
 assert((flags&(MS_RDONLY|MS_NOSUID|MS_NODEV|MS_NOEXEC|MS_NOATIME))==(MS_RDONLY|MS_NOSUID|MS_NODEV|MS_NOEXEC|MS_NOATIME));
 struct card cards[2]={c,{.state="No card"}};char targets[2][PATH_MAX]={"run/TF1","run/TF2"};bool ready[2]={true,false};
 assert(publish(cards,targets,ready));char line[100];assert(text("run/roots",line,sizeof line)&&!strcmp(line,"run/TF1"));
 assert(!rmdir("run/TF1/Games"));game_saves=true;assert(discover(&c,"run/TF1"));assert(!(flags&MS_RDONLY));assert((flags&(MS_NOSUID|MS_NODEV|MS_NOEXEC|MS_NOATIME))==(MS_NOSUID|MS_NODEV|MS_NOEXEC|MS_NOATIME));assert(!rmdir("run/TF1/Games"));games=false;assert(!discover(&c,"run/TF1"));assert(unmounts_count==1);
 write_file("fe2b0000.mmc/mmcblk9/device/type","MMC\n");assert(!find_card(0,&c,true));
 write_file("fe2b0000.mmc/mmcblk9/device/type","SD\n");assert(!unlink("sys/mmcblk9"));assert(!find_card(0,&c,true));
 return 0;
}
'''
class NativeSD(unittest.TestCase):
 def test_policy_identity_and_mount_flow(self):
  cc=shlex.split(os.environ.get('SLOT_TEST_CC','cc'))
  with tempfile.TemporaryDirectory()as d:
   d=Path(d);src=d/'test.c';src.write_text(TEST);binary=d/'test'
   subprocess.run([*cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(SOURCE.parent),str(src),'-lblkid','-o',str(binary)],check=True)
   images=[d/'sd.img',d/'blank.img',d/'other.img']
   for p in images:
    with p.open('wb')as f:f.truncate(32*1024**2)
   subprocess.run(['mkfs.exfat','-L','SLOT',str(images[0])],check=True,stdout=subprocess.DEVNULL)
   subprocess.run(['mkfs.ext4','-F','-q',str(images[2])],check=True,stdout=subprocess.DEVNULL)
   uuid=subprocess.check_output(['blkid','-p','-s','UUID','-o','value',str(images[0])],text=True).strip()
   subprocess.run([str(binary),str(images[0]),str(images[1]),uuid,str(images[2])],check=True)
if __name__=='__main__':unittest.main()
