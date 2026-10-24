// SPDX-License-Identifier: GPL-3.0-or-later
// RG353V boot-only card discovery. Python remains the on-demand storage UI.
#define _GNU_SOURCE
#include <blkid/blkid.h>
#include <ctype.h>
#include <fcntl.h>
#include <glob.h>
#include <limits.h>
#include <mntent.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

static const char *sysblocks="/sys/class/block";
static const char *mountfile="/proc/self/mounts";
static const char *base="/run/slot-sd-library";
static const char *controllers[]={"/fe2b0000.mmc/","/fe2c0000.mmc/"};
static const char *slots[]={"TF1","TF2"};
static bool game_saves=false;
struct card { char node[PATH_MAX], device[PATH_MAX], serial[80]; const char *state; };

static bool text(const char *path,char *out,size_t cap) {
    FILE *f=fopen(path,"re"); if(!f)return false;
    bool ok=fgets(out,(int)cap,f)!=NULL && !ferror(f); fclose(f);
    if(ok)out[strcspn(out,"\r\n")]=0;
    return ok;
}
static bool disk_name(const char *name) {
    if(strncmp(name,"mmcblk",6)||!isdigit((unsigned char)name[6]))return false;
    for(const char *p=name+6;*p;p++)if(!isdigit((unsigned char)*p))return false;
    return true;
}
static bool same_disk(const char *source,const char *disk) {
    size_t n=strlen(disk);
    if(strncmp(source,disk,n))return false;
    if(!source[n])return true;
    if(source[n++]!='p'||!isdigit((unsigned char)source[n]))return false;
    for(;source[n];n++)if(!isdigit((unsigned char)source[n]))return false;
    return true;
}
static bool protected_disk(const char *disk,bool content) {
    FILE *f=setmntent(mountfile,"r"); if(!f)return true;
    struct mntent e,*p; char buf[16384],real[PATH_MAX]; bool protected=false;
    while((p=getmntent_r(f,&e,buf,sizeof buf))) {
        if(strcmp(p->mnt_dir,"/flash")&&strcmp(p->mnt_dir,"/storage")&&
           (!content||strcmp(p->mnt_dir,"/storage/slotcontent")))continue;
        if(!realpath(p->mnt_fsname,real)){protected=true;break;}
        if(same_disk(real,disk)){protected=true;break;}
    }
    if(ferror(f))protected=true;
    endmntent(f);return protected;
}
static bool mounted_anywhere(const char *device) {
    FILE *f=setmntent(mountfile,"r"); if(!f)return true;
    struct mntent e,*p;char buf[16384],real[PATH_MAX];bool found=false;
    while((p=getmntent_r(f,&e,buf,sizeof buf)))
        if(realpath(p->mnt_fsname,real)&&!strcmp(real,device)){found=true;break;}
    if(ferror(f))found=true;
    endmntent(f);return found;
}
static bool block_device(const char *node,char *device) {
    const char *name=strrchr(node,'/');if(!name)return false;name++;
    if(snprintf(device,PATH_MAX,"/dev/%s",name)>=PATH_MAX)return false;
    char path[PATH_MAX],value[80]; unsigned ma,mi;char extra;
    if(snprintf(path,sizeof path,"%s/dev",node)>=(int)sizeof path||!text(path,value,sizeof value)||
       sscanf(value,"%u:%u%c",&ma,&mi,&extra)!=2)return false;
    struct stat st;
    return !lstat(device,&st)&&S_ISBLK(st.st_mode)&&st.st_rdev==makedev(ma,mi);
}
static bool filesystem(const char *device,const char *uuid) {
    blkid_probe p=blkid_new_probe_from_filename(device);if(!p)return false;
    const char *v=NULL;size_t n=0;
    bool ok=!blkid_probe_enable_partitions(p,0)&&!blkid_probe_enable_superblocks(p,1)&&
        !blkid_probe_set_superblocks_flags(p,BLKID_SUBLKS_TYPE|BLKID_SUBLKS_UUID)&&
        !blkid_do_safeprobe(p)&&!blkid_probe_lookup_value(p,"TYPE",&v,&n)&&n==6&&!memcmp(v,"exfat",6);
    if(ok&&uuid)ok=!blkid_probe_lookup_value(p,"UUID",&v,&n)&&n==strlen(uuid)+1&&!memcmp(v,uuid,n);
    blkid_free_probe(p);return ok;
}
static bool find_card(unsigned slot,struct card *card,bool content) {
    char pattern[PATH_MAX];glob_t g={0};unsigned found=0;
    if(snprintf(pattern,sizeof pattern,"%s/mmcblk*",sysblocks)>=(int)sizeof pattern)return false;
    if(glob(pattern,0,NULL,&g))return false;
    for(size_t i=0;i<g.gl_pathc;i++) {
        const char *node=g.gl_pathv[i],*name=strrchr(node,'/');char real[PATH_MAX],path[PATH_MAX],type[16],dev[PATH_MAX];
        if(!name||!disk_name(name+1)||!realpath(node,real)||!strstr(real,controllers[slot]))continue;
        if(snprintf(path,sizeof path,"%s/device/type",node)>=(int)sizeof path||!text(path,type,sizeof type)||strcmp(type,"SD"))continue;
        if(!block_device(node,dev)||protected_disk(dev,content))continue;
        if(++found!=1)break;
        strcpy(card->node,node);strcpy(card->device,dev);
        if(snprintf(path,sizeof path,"%s/device/serial",node)>=(int)sizeof path||!text(path,card->serial,sizeof card->serial)){found=0;break;}
        for(char *p=card->serial;*p;p++)if(!isalnum((unsigned char)*p)){found=0;break;}
    }
    globfree(&g);return found==1;
}
static bool directory(const char *path) {
    if(mkdir(path,0755)&&access(path,F_OK))return false;
    struct stat st;return !lstat(path,&st)&&S_ISDIR(st.st_mode)&&st.st_uid==0&&!(st.st_mode&022);
}
static bool discover(struct card *c,const char *target) {
    char pattern[PATH_MAX];glob_t g={0};
    const char *name=strrchr(c->node,'/')+1;
    if(snprintf(pattern,sizeof pattern,"%s/%sp*",c->node,name)>=(int)sizeof pattern)return false;
    int rc=glob(pattern,0,NULL,&g);
    if(rc&&rc!=GLOB_NOMATCH)return false;
    bool accepted=false;
    for(size_t i=0;i<(g.gl_pathc?g.gl_pathc:1);i++) {
        char dev[PATH_MAX],games[PATH_MAX];const char *node=g.gl_pathc?g.gl_pathv[i]:c->node;
        if(!block_device(node,dev)||mounted_anywhere(dev)||!filesystem(dev,NULL))continue;
        if(mount(dev,target,"exfat",(game_saves?0:MS_RDONLY)|MS_NOSUID|MS_NODEV|MS_NOEXEC|MS_NOATIME,NULL)){c->state="Read error";continue;}
        struct stat st;
        if(snprintf(games,sizeof games,"%s/Games",target)<(int)sizeof games&&!stat(games,&st)&&S_ISDIR(st.st_mode)){
            c->state="Ready";strcpy(c->device,dev);accepted=true;break;
        }
        if(umount(target)){c->state="Busy";break;}
    }
    globfree(&g);return accepted;
}
static FILE *output(const char *name,char *tmp,char *dest) {
    if(snprintf(tmp,PATH_MAX,"%s/.%s.new",base,name)>=PATH_MAX||snprintf(dest,PATH_MAX,"%s/%s",base,name)>=PATH_MAX)return NULL;
    int fd=open(tmp,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0644);return fd<0?NULL:fdopen(fd,"w");
}
static bool publish(struct card *cards,char targets[2][PATH_MAX],bool *ready) {
    char tmp[PATH_MAX],dest[PATH_MAX];FILE *f=output("roots",tmp,dest);if(!f)return false;
    for(unsigned i=0;i<2;i++)if(ready[i])fprintf(f,"%s\n",targets[i]);
    if(fclose(f)||rename(tmp,dest))return false;
    f=output("status.json",tmp,dest);if(!f)return false;
    fputs("{\"schema\":1,\"cards\":[",f);
    for(unsigned i=0;i<2;i++) {
        fprintf(f,"%s{\"slot\":\"%s\",\"state\":\"%s\"",i?",":"",slots[i],cards[i].state);
        if(ready[i])fprintf(f,",\"serial\":\"%s\",\"device\":\"%s\",\"readonly\":%s,\"root\":\"%s\"",cards[i].serial,cards[i].device,game_saves?"false":"true",targets[i]);
        fputc('}',f);
    }
    fputs("]}\n",f);return !fclose(f)&&!rename(tmp,dest);
}
int main(int argc,char **argv) {
    (void)argv;
    if(geteuid()!=0)return 1;
    char model[80];
    if(!text("/proc/device-tree/model",model,sizeof model)||strcmp(model,"Anbernic RG353V"))return 1;
    if(argc!=1||!directory(base))return 1;
    char existing[PATH_MAX];
    if(snprintf(existing,sizeof existing,"%s/status.json",base)>=(int)sizeof existing)return 1;
    // Boot starts with empty /run. A manual service retry uses the established
    // refresh path, which reconciles existing mounts and ejection markers.
    if(!access(existing,F_OK)) {
        execl("/usr/bin/slot-sd-library","slot-sd-library","refresh",(char *)NULL);return 1;
    }
    char lock[PATH_MAX];if(snprintf(lock,sizeof lock,"%s/lock",base)>=(int)sizeof lock)return 1;
    int fd=open(lock,O_RDWR|O_CREAT|O_NOFOLLOW,0600);if(fd<0||flock(fd,LOCK_EX))return 1;
    char policy[16];
    game_saves=text("/storage/slotcontent/Config/save-location",policy,sizeof policy)&&!strcmp(policy,"game");
    struct card cards[2]={0};char targets[2][PATH_MAX];bool ready[2]={false,false};
    for(unsigned i=0;i<2;i++) {
        cards[i].state="No card";
        if(snprintf(targets[i],sizeof targets[i],"%s/%s",base,slots[i])>=(int)sizeof targets[i]||!directory(targets[i]))return 1;
        char marker[PATH_MAX];if(snprintf(marker,sizeof marker,"%s/%s.ejected",base,slots[i])>=(int)sizeof marker)return 1;
        if(!access(marker,F_OK)){cards[i].state="Safe to remove";continue;}
        if(!find_card(i,&cards[i],true))continue;
        cards[i].state="No exFAT Games folder";
        ready[i]=discover(&cards[i],targets[i]);
    }
    bool ok=publish(cards,targets,ready);close(fd);return ok?0:1;
}
