#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

static int text(const char *path, char *out, size_t cap) {
    FILE *f=fopen(path,"r"); if(!f)return -1;
    int ok=fgets(out,cap,f)!=NULL; fclose(f);
    if(ok)out[strcspn(out,"\r\n")]=0;
    return ok?0:-1;
}
static int protect(const char *name) {
    char path[256];snprintf(path,sizeof path,"/dev/%s",name);
    int fd=open(path,O_RDONLY|O_CLOEXEC); if(fd<0)return -1;
    struct stat st;int ro=1;
    int result=fstat(fd,&st) || !S_ISBLK(st.st_mode) || ioctl(fd,BLKROSET,&ro) || ioctl(fd,BLKROGET,&ro) || ro!=1;
    close(fd);if(!result)printf("SD test: %s read-only\n",name);
    return result?-1:0;
}
int main(void) {
    char model[128];
    if(text("/sys/firmware/devicetree/base/compatible",model,sizeof model) || strcmp(model,"anbernic,rg353v"))return 1;
    FILE *f=fopen("/proc/mounts","r");if(!f)return 1;
    char dev[256],mount[256],line[2048],source[128]="";
    while(fgets(line,sizeof line,f))if(sscanf(line,"%255s %255s",dev,mount)==2 && !strcmp(mount,"/flash")) {
        unsigned n,part;char extra;
        if(sscanf(dev,"/dev/mmcblk%up%u%c",&n,&part,&extra)==2 && part==1)snprintf(source,sizeof source,"mmcblk%u",n);
    }
    fclose(f);if(!*source){fprintf(stderr,"SD test: boot source is not an SD partition\n");return 1;}
    char path[256],type[64];snprintf(path,sizeof path,"/sys/class/block/%s/device/type",source);
    if(text(path,type,sizeof type)||strcmp(type,"SD")){fprintf(stderr,"SD test refuses internal boot\n");return 1;}
    DIR *d=opendir("/sys/class/block");if(!d)return 1;
    char internal[8][128];size_t count=0;struct dirent *e;
    while((e=readdir(d))) {
        unsigned n;char extra;
        if(sscanf(e->d_name,"mmcblk%u%c",&n,&extra)!=1)continue;
        snprintf(path,sizeof path,"/sys/class/block/%s/device/type",e->d_name);
        if(!text(path,type,sizeof type) && !strcmp(type,"MMC")) {
            if(count==8){closedir(d);return 1;}
            snprintf(internal[count++],128,"mmcblk%u",n);
        }
    }
    closedir(d);
    if(!count){fprintf(stderr,"SD test: internal storage identity unavailable\n");return 1;}
    for(size_t i=0;i<count;i++) {
        if(protect(internal[i]))return 1;
        d=opendir("/sys/class/block");if(!d)return 1;
        while((e=readdir(d)))if(!strncmp(e->d_name,internal[i],strlen(internal[i])) && strcmp(e->d_name,internal[i])) {
            const char *tail=e->d_name+strlen(internal[i]);
            if((*tail=='p' || !strncmp(tail,"boot",4)) && protect(e->d_name)){closedir(d);return 1;}
        }
        closedir(d);
    }
    return 0;
}
