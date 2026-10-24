// SPDX-License-Identifier: GPL-3.0-or-later
// Optional page-cache hints; never executes driver code or gates frontend startup.
// Header fingerprints identify this measured layout, not an execution trust boundary.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#define PAGE 4096
#define MAX_BYTES (256ULL<<20)
#define BUDGET (48ULL<<20)
static uint64_t fingerprint(int fd){
 unsigned char bytes[PAGE];ssize_t n=pread(fd,bytes,sizeof bytes,0);if(n<=0)return 0;
 uint64_t h=UINT64_C(14695981039346656037);for(ssize_t i=0;i<n;i++){h^=bytes[i];h*=UINT64_C(1099511628211);}return h;
}
#ifdef SLOT_PREFETCH_CAPTURE
static int capture(const char *path){
 int fd=open(path,O_RDONLY|O_CLOEXEC|O_NONBLOCK);struct stat st;
 if(fd<0||fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<=0||(uint64_t)st.st_size>MAX_BYTES)return 1;
 size_t pages=((size_t)st.st_size+PAGE-1)/PAGE;unsigned char *resident=calloc(pages,1);if(!resident)return 1;
 void *map=mmap(NULL,(size_t)st.st_size,PROT_READ,MAP_SHARED,fd,0);if(map==MAP_FAILED)return 1;
 if(mincore(map,(size_t)st.st_size,resident))return 1;
 printf("FILE %s %"PRIu64" %016"PRIx64"\n",path,(uint64_t)st.st_size,fingerprint(fd));
 for(size_t i=0;i<pages;){if(!(resident[i]&1)){i++;continue;}size_t begin=i;while(i<pages&&(resident[i]&1))i++;printf("RANGE %zu %zu\n",begin*PAGE,(i-begin)*PAGE);}
 puts("END");munmap(map,(size_t)st.st_size);free(resident);close(fd);return 0;
}
#endif
int main(int argc,char **argv){
 if(sysconf(_SC_PAGESIZE)!=PAGE)return 0;
 #ifdef SLOT_PREFETCH_CAPTURE
 if(argc>=3&&!strcmp(argv[1],"--capture")){puts("SLOT-PREFETCH-1 4096");for(int i=2;i<argc;i++)if(capture(argv[i]))return 1;return 0;}
 #endif
 if(argc!=2)return 2;
 FILE *f=fopen(argv[1],"r");if(!f)return 0;
 char line[8192],path[4096],extra;int fd=-1;uint64_t size=0,pin=0,total=0,advised=0;unsigned files=0,ranges=0,matched=0;int active=0,valid=1;
 if(!fgets(line,sizeof line,f)||strcmp(line,"SLOT-PREFETCH-1 4096\n")){fclose(f);return 0;}
 while(fgets(line,sizeof line,f)){
  uint64_t off,len;
  if(!strncmp(line,"FILE ",5)){
   if(active||++files>8||sscanf(line,"FILE %4095s %"SCNu64" %"SCNx64" %c",path,&size,&pin,&extra)!=3||path[0]!='/'||!size||size>MAX_BYTES){valid=0;break;}
   active=1;fd=open(path,O_RDONLY|O_CLOEXEC|O_NONBLOCK);struct stat st;
   if(fd>=0&&(fstat(fd,&st)||!S_ISREG(st.st_mode)||(uint64_t)st.st_size!=size||fingerprint(fd)!=pin)){close(fd);fd=-1;}
   if(fd>=0)matched++;
  }else if(!strncmp(line,"RANGE ",6)){
   if(!active||++ranges>4096||sscanf(line,"RANGE %"SCNu64" %"SCNu64" %c",&off,&len,&extra)!=2||!len||off%PAGE||len%PAGE||off>=size||len>((size+PAGE-1)/PAGE)*PAGE-off||len>BUDGET-total){valid=0;break;}
   total+=len;
   if(fd>=0 && !posix_fadvise(fd,(off_t)off,(off_t)len,POSIX_FADV_WILLNEED))advised+=len;
  }else if(!strcmp(line,"END\n")){
   if(!active){valid=0;break;}if(fd>=0)close(fd);fd=-1;active=0;
  }else{valid=0;break;}
 }
 if(fd>=0)close(fd);
 if(active||ferror(f))valid=0;
 fclose(f);
 fprintf(stderr,"Slot graphics prefetch: %s; %u files, %u matched, %u ranges, %"PRIu64" KiB advised\n",valid?"complete":"stopped",files,matched,ranges,advised/1024);
 return 0;
}
