// SPDX-License-Identifier: GPL-3.0-or-later
// Verify a confirmed revision in one process. Runtime mode defers only the
// source archive and opt-in emulator cores; launch verifies sealed core bytes.
// Metadata, inventory and frontend code stay synchronous.
// A failure invokes the full updater; this never confirms an update trial.
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <openssl/evp.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <unistd.h>

#define LIMIT 8192
struct entry { char *path; unsigned mode; bool seen; };
struct checksum { char *path; char hash[65]; bool checked, deferred; };
static struct entry entries[LIMIT];
static struct checksum sums[LIMIT];
static size_t nentries, nsums;
static char system_root[PATH_MAX];
static void fail(void) { exit(1); }
static void join(char *out, const char *a, const char *b) {
    if (snprintf(out, PATH_MAX, "%s/%s", a, b) >= PATH_MAX) fail();
}
static char *line(FILE *f, char *out) {
    if (!fgets(out, PATH_MAX + 80, f)) fail();
    size_t n = strlen(out);
    if (!n || out[n-1] != '\n' || strchr(out, '\r') || strchr(out, '\\')) fail();
    out[n-1] = 0;
    return out;
}
static struct checksum *find_sum(const char *p) {
    for (size_t i=0; i<nsums; i++) if (!strcmp(p, sums[i].path)) return &sums[i];
    return NULL;
}
static bool directory(const char *p) {
    struct stat s;
    return !lstat(p, &s) && S_ISDIR(s.st_mode);
}
static bool relative(const char *p) {
    if (!*p || *p=='/' || strlen(p)>=PATH_MAX) return false;
    const char *start=p;
    for (;;) {
        const char *end=strchr(start, '/');
        size_t n=end ? (size_t)(end-start) : strlen(start);
        if (!n || (n==1 && *start=='.') || (n==2 && !strncmp(start,"..",2))) return false;
        if (!end) return true;
        start=end+1;
    }
}
static void digest(const char *p, char *out) {
    int fd=open(p, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
    struct stat s;
    if (fd<0 || fstat(fd,&s) || !S_ISREG(s.st_mode)) fail();
    EVP_MD_CTX *ctx=EVP_MD_CTX_new();
    if (!ctx || !EVP_DigestInit_ex(ctx, EVP_sha256(), NULL)) fail();
    unsigned char buffer[262144], sum[EVP_MAX_MD_SIZE];
    ssize_t n; unsigned len=0;
    while ((n=read(fd,buffer,sizeof buffer))>0)
        if (!EVP_DigestUpdate(ctx,buffer,(size_t)n)) fail();
    if (n<0 || !EVP_DigestFinal_ex(ctx,sum,&len) || len!=32) fail();
    close(fd); EVP_MD_CTX_free(ctx);
    for (unsigned i=0;i<32;i++) sprintf(out+2*i,"%02x",sum[i]);
}
// The caller owns this memfd and loads it only after successful verification.
// No pathname is reopened after hashing, so dlopen sees precisely these bytes.
static int core_snapshot(const char *expected, const char *path) {
    if (strlen(expected)!=64 || strspn(expected,"0123456789abcdef")!=64) fail();
    const char *name=strrchr(path,'/');
    if (path[0]!='/' || !name || (strcmp(name+1,"mgba_libretro.so") &&
                                strcmp(name+1,"gpsp_libretro.so"))) fail();
    struct stat source, target;
    if (fstat(STDOUT_FILENO,&target) || !S_ISREG(target.st_mode) || target.st_size ||
        fcntl(STDOUT_FILENO,F_GET_SEALS)!=0 || lseek(STDOUT_FILENO,0,SEEK_CUR)!=0) fail();
    int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
    if (fd<0 || fstat(fd,&source) || !S_ISREG(source.st_mode) ||
        !(source.st_mode&0111) || source.st_size<=0 || source.st_size>64*1024*1024) fail();
    EVP_MD_CTX *ctx=EVP_MD_CTX_new();
    if (!ctx || !EVP_DigestInit_ex(ctx,EVP_sha256(),NULL)) fail();
    unsigned char buffer[262144], sum[EVP_MAX_MD_SIZE];
    ssize_t n; unsigned len=0; off_t copied=0;
    while ((n=read(fd,buffer,sizeof buffer))>0) {
        if (!EVP_DigestUpdate(ctx,buffer,(size_t)n)) fail();
        copied+=n; if (copied>64*1024*1024) fail();
        for (ssize_t offset=0;offset<n;) {
            ssize_t written=write(STDOUT_FILENO,buffer+offset,(size_t)(n-offset));
            if (written<=0) fail();
            offset+=written;
        }
    }
    if (n<0 || copied!=source.st_size || !EVP_DigestFinal_ex(ctx,sum,&len) || len!=32) fail();
    close(fd); EVP_MD_CTX_free(ctx);
    char actual[65];
    for (unsigned i=0;i<32;i++) sprintf(actual+2*i,"%02x",sum[i]);
    if (memcmp(actual,expected,64) || fcntl(STDOUT_FILENO,F_ADD_SEALS,
            F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL)) fail();
    return 0;
}
static bool emulator(const char *path) {
    return !strcmp(path,"mgba_libretro.so") || !strcmp(path,"gpsp_libretro.so");
}
static void verify(const char *path) {
    struct checksum *s=find_sum(path);
    char actual[65];
    if (!s) fail();
    if (s->checked) return;
    digest(path,actual);
    if (memcmp(s->hash,actual,64)) fail();
    s->checked=true;
}
static void checksums(const char *path) {
    FILE *f=fopen(path,"r"); if (!f) fail();
    char buf[PATH_MAX+80];
    while (fgets(buf,sizeof buf,f)) {
        size_t n=strlen(buf);
        if (n<69 || buf[n-1]!='\n' || buf[64]!=' ' || buf[65]!=' ' || buf[66]!='/') fail();
        buf[n-1]=0;
        if (strchr(buf,'\r') || strchr(buf,'\\')) fail();
        for (int i=0;i<64;i++) if (!strchr("0123456789abcdef",buf[i])) fail();
        char *p=buf+66;
        if (strlen(p)>=PATH_MAX || find_sum(p) || nsums==LIMIT) fail();
        sums[nsums].path=strdup(p);
        if (!sums[nsums].path) fail();
        memcpy(sums[nsums].hash,buf,64);
        sums[nsums++].hash[64]=0;
    }
    if (ferror(f)) fail();
    fclose(f);
}
static int cmp(const void *a, const void *b) {
    return strcmp(((const struct entry *)a)->path,((const struct entry *)b)->path);
}
static void walk(int fd, const char *prefix) {
    DIR *dir=fdopendir(fd); if (!dir) fail();
    struct dirent *de;
    while ((de=readdir(dir))) {
        if (!strcmp(de->d_name,".") || !strcmp(de->d_name,"..")) continue;
        char path[PATH_MAX];
        if (*prefix) join(path,prefix,de->d_name);
        else if (snprintf(path,sizeof path,"%s",de->d_name)>=PATH_MAX) fail();
        struct stat s;
        if (fstatat(fd,de->d_name,&s,AT_SYMLINK_NOFOLLOW)) fail();
        if (S_ISDIR(s.st_mode)) {
            int child=openat(fd,de->d_name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
            if (child<0) fail();
            walk(child,path);
        } else if (S_ISREG(s.st_mode)) {
            struct entry key={.path=path};
            struct entry *e=bsearch(&key,entries,nentries,sizeof entries[0],cmp);
            if (!e || e->seen || e->mode != ((s.st_mode & 0111) ? 0755u : 0644u)) fail();
            char full[PATH_MAX]; join(full,system_root,path);
            if (!find_sum(full)) fail();
            e->seen=true;
        } else fail();
    }
    closedir(dir);
}
int main(int argc,char **argv) {
    if (argc==4 && !strcmp(argv[1],"--core")) return core_snapshot(argv[2],argv[3]);
    bool runtime=argc==3 && !strcmp(argv[1],"--runtime");
    if (argc==3 && !runtime && strcmp(argv[1],"--all")) fail();
    if (argc!=2 && argc!=3) fail();
    const char *manager=argv[argc-1];
    if (manager[0]!='/' || !directory(manager)) fail();
    char p[PATH_MAX], buf[PATH_MAX+80], recipe[PATH_MAX], inventory[PATH_MAX];
    join(p,manager,"normal-boot-audit.failed");
    struct stat failure;
    if (runtime && (!lstat(p,&failure) || errno!=ENOENT)) fail();
    join(p,manager,"normal-boot-v2.sha256"); checksums(p);
    join(recipe,manager,"normal-boot-v2.sh"); verify(recipe);
    join(inventory,manager,"normal-boot-v2.inventory"); verify(inventory);
    join(p,manager,"state.json"); verify(p);
    FILE *f=fopen(inventory,"r"); if (!f) fail();
    if (strcmp(line(f,buf),"SLOT-BOOT-2")) fail();
    struct utsname u; if (uname(&u) || strcmp(line(f,buf),u.release)) fail();
    line(f,buf);
    if (strlen(buf)>=PATH_MAX) fail();
    strcpy(system_root,buf);
    join(p,manager,"revisions"); if (!directory(p)) fail();
    size_t prefix=strlen(p);
    if (strncmp(buf,p,prefix) || buf[prefix]!='/') fail();
    const char *id=buf+prefix+1; const char *tail=strchr(id,'/');
    if (!tail || tail==id || strcmp(tail,"/System")) fail();
    for (const char *c=id;c<tail;c++)
        if (!strchr("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.",*c)) fail();
    if ((tail-id==1 && *id=='.') || (tail-id==2 && !strncmp(id,"..",2))) fail();
    memcpy(p,buf,(size_t)(tail-buf)); p[tail-buf]=0;
    if (!directory(p) || !directory(system_root)) fail();
    // Reconstruct without overlapping snprintf operands.
    char parent[PATH_MAX]; memcpy(parent,buf,(size_t)(tail-buf)); parent[tail-buf]=0;
    join(p,parent,"revision.json"); verify(p);
    line(f,buf);
    char *end; unsigned long runtimes=strtoul(buf,&end,10);
    if (!*buf || *end || runtimes>32) fail();
    for (unsigned long i=0;i<runtimes;i++) verify(line(f,buf));
    while (fgets(buf,sizeof buf,f)) {
        size_t n=strlen(buf);
        if (n<6 || buf[n-1]!='\n' || buf[3]!=' ' || nentries==LIMIT) fail();
        buf[n-1]=0;
        unsigned mode;
        if (!strncmp(buf,"755 ",4)) mode=0755;
        else if (!strncmp(buf,"644 ",4)) mode=0644;
        else { fail(); mode=0; }
        if (!relative(buf+4) || strchr(buf,'\r') || strchr(buf,'\\')) fail();
        entries[nentries++]=(struct entry){.path=strdup(buf+4),.mode=mode};
        if (!entries[nentries-1].path) fail();
    }
    if (ferror(f) || !nentries) fail();
    fclose(f); qsort(entries,nentries,sizeof entries[0],cmp);
    for (size_t i=1;i<nentries;i++) if (!strcmp(entries[i-1].path,entries[i].path)) fail();
    int fd=open(system_root,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if (fd<0) fail();
    walk(fd,"");
    bool sealed_cores=false;
    for (size_t i=0;i<nentries;i++) {
        if (!strcmp(entries[i].path,"core-verification-v1")) {
            if (entries[i].mode!=0644) fail();
            join(p,system_root,entries[i].path); verify(p);
            FILE *marker=fopen(p,"r"); if (!marker) fail();
            if (!fgets(buf,sizeof buf,marker) || strcmp(buf,"SLOT-CORE-SEALED-1\n") ||
                fgetc(marker)!=EOF || ferror(marker)) fail();
            fclose(marker); sealed_cores=true;
        }
    }
    for (size_t i=0;i<nentries;i++) {
        if (!entries[i].seen) fail();
        bool deferred=runtime && ((entries[i].mode==0644 &&
            !strcmp(entries[i].path,"licenses/slot-source.tar.gz")) ||
            (sealed_cores && entries[i].mode==0755 && emulator(entries[i].path)));
        join(p,system_root,entries[i].path);
        if (deferred) find_sum(p)->deferred=true;
        else verify(p);
    }
    for (size_t i=0;i<nsums;i++)
        if (!sums[i].deferred) verify(sums[i].path);
    return 0;
}
