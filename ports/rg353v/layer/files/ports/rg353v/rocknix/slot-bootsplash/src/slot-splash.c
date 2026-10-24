// SPDX-License-Identifier: GPL-2.0-or-later
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#ifdef __linux__
#include <linux/fb.h>
#include <linux/kd.h>
#ifndef SLOT_SPLASH_INIT
#include <poll.h>
#include <sys/inotify.h>
#endif
#include <sys/ioctl.h>
#include <sys/mman.h>
#endif
#include "brand.h"
#include "plan.h"
#define W 640
#define H 480
#ifndef ROOT
#define ROOT "/run/slot-boot"
#endif
static uint8_t pixels[W*H*4],backdrop[W*H*4];
static int backdrop_ready;
#ifdef __linux__
static volatile sig_atomic_t stopping;
static void stop_signal(int sig) { (void)sig; stopping=1; }
static double seconds(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9; }
#endif
static int exists(const char *name) { char path[256];snprintf(path,sizeof(path),ROOT"/%s",name);return access(path,F_OK)==0; }
#ifdef __linux__
static void touch(const char *name) { char path[256];snprintf(path,sizeof(path),ROOT"/%s",name);int fd=open(path,O_WRONLY|O_CREAT|O_CLOEXEC,0600);if(fd>=0)close(fd); }
#endif
static int stamp(const char *name) {
 char path[256],value[48];struct timespec t;
 if(clock_gettime(CLOCK_MONOTONIC,&t))return 1;
 snprintf(path,sizeof(path),ROOT"/%s",name);
 int fd=open(path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);
 if(fd<0)return errno==EEXIST?0:1;
 int n=snprintf(value,sizeof(value),"%lld.%09ld\n",(long long)t.tv_sec,t.tv_nsec);
 int ok=write(fd,value,(size_t)n)==n;close(fd);return ok?0:1;
}
static int milestone(const char *id) {
 for(unsigned i=0;i<STEP_COUNT;i++)if(!strcmp(id,steps[i]))return 1;
 if(strncmp(id,"hardware-",9)||strlen(id)>120||strlen(id)<=9)return 0;
 for(const char *p=id+9;*p;p++)if(!((*p>='a'&&*p<='z')||(*p>='A'&&*p<='Z')||(*p>='0'&&*p<='9')||*p=='-'||*p=='_'||*p=='.'))return 0;
 return strstr(id,"..")?0:1;
}
static int record(const char *kind,const char *id) {
 if((strcmp(kind,"--event")&&strcmp(kind,"--begin"))||!milestone(id))return 2;
 mkdir(ROOT"/begins",0700);
 char n[192];snprintf(n,sizeof(n),"%s/%s",!strcmp(kind,"--begin")?"begins":"events",id);
 return stamp(n);
}
static int stream_marks(void) {
 char line[192],kind[16],id[128],extra;
 while(fgets(line,sizeof(line),stdin)) {
  size_t n=strlen(line);
  if(!n||line[n-1]!='\n'||sscanf(line,"%15s %127s %c",kind,id,&extra)!=2)return 2;
  int result=record(kind,id);if(result)return result;
  /* An acknowledgement makes each timestamp precede the shell's next step. */
  if(fputs("ok\n",stdout)==EOF||fflush(stdout))return 1;
 }
 return ferror(stdin)?1:0;
}
static int percentage(void) {
 unsigned done=0;char p[256];
 for(unsigned i=0;i<STEP_COUNT;i++){snprintf(p,sizeof(p),ROOT"/events/%s",steps[i]);done+=access(p,F_OK)==0;}
 int n=(int)(100*done/STEP_COUNT);
 return n==100 && !exists("events/frontend-ready")?99:n;
}
static void blend(int x,int y,float r,float g,float b,float a) {
 if(x<0||y<0||x>=W||y>=H)return;
 uint8_t *p=pixels+(y*W+x)*4;a=fmaxf(0,fminf(a,1));
 p[0]=(uint8_t)(p[0]+(r-p[0])*a);p[1]=(uint8_t)(p[1]+(g-p[1])*a);p[2]=(uint8_t)(p[2]+(b-p[2])*a);
}
static void mask(const unsigned char *m,int w,int h,int x0,int y0,float a) {
 for(int y=0;y<h;y++)for(int x=0;x<w;x++)blend(x+x0,y+y0,244,245,249,a*m[y*w+x]/255.f);
}
static float capsule(int x,int y,float length,float height) {
 float cx=fmaxf(height/2,fminf((float)x,length-height/2));
 return hypotf(x-cx,y-height/2)-height/2;
}
static void scene(float value,int number,double phase,float fade) {
 if(!backdrop_ready)for(int y=0;y<H;y++)for(int x=0;x<W;x++){
  float glow=expf(-((x-320.f)*(x-320.f)/30000.f+(y-280.f)*(y-280.f)/12000.f));
  uint8_t *p=backdrop+(y*W+x)*4;p[0]=(uint8_t)(7+glow*1);p[1]=(uint8_t)(9+glow*4);p[2]=(uint8_t)(15+glow*7);p[3]=255;
 }
 backdrop_ready=1;memcpy(pixels,backdrop,sizeof(pixels));
 mask(logo,logo_w,logo_h,(W-logo_w)/2,174,fade);
 const int left=170,top=275,length=300,height=7;
 float fill=length*fmaxf(0,fminf(value,100))/100;
 for(int y=-16;y<height+17;y++)for(int x=-16;x<length+17;x++){
  float d=capsule(x,y,length,height);
  float edge=fmaxf(0,1-fabsf(d));
  blend(left+x,top+y,29,65,84,edge*.95f);
  if(fill>0){
   float fd=capsule(x,y,fmaxf(fill,height),height);
   if(x<=fill){
    float light=.82f+.12f*sinf((float)phase*2.f-x*.025f);
    blend(left+x,top+y,43,199,237,expf(-fmaxf(fd,0)/3.2f)*.22f*fade);
    blend(left+x,top+y,83,224,249,fmaxf(0,fminf(1,1-fd))*light*fade);
   }
  }
 }
 char text[8];snprintf(text,sizeof(text),"%d%%",number);int width=0;
 for(unsigned i=0;i<strlen(text);i++){int d=text[i]=='%'?10:text[i]-'0';width+=digits_w[d]+1;}
 int x=(W-width)/2;
 for(unsigned i=0;i<strlen(text);i++){int d=text[i]=='%'?10:text[i]-'0';mask(digits[d],digits_w[d],digits_h[d],x,306,.8f*fade);x+=digits_w[d]+1;}
}
static int save(const char *path,int ppm) {
 FILE *f=fopen(path,"wb");if(!f)return -1;
 if(ppm){fprintf(f,"P6\n%d %d\n255\n",W,H);for(int n=0;n<W*H;n++)if(fwrite(pixels+n*4,1,3,f)!=3){fclose(f);return -1;}}
 else if(fwrite(pixels,1,sizeof(pixels),f)!=sizeof(pixels)){fclose(f);return -1;}
 return fclose(f);
}
#ifdef __linux__
static int console_mode(int mode) {int fd=open("/dev/tty0",O_RDWR|O_CLOEXEC);if(fd<0)return -1;int r=ioctl(fd,KDSETMODE,mode);close(fd);return r;}
#ifndef SLOT_SPLASH_INIT
static int handoff_ready(void) {return stopping||exists("handoff")||exists("failed");}
static int watch_handoff(void) {
 int fd=inotify_init1(IN_NONBLOCK|IN_CLOEXEC);
 if(fd>=0&&inotify_add_watch(fd,ROOT,IN_CREATE|IN_MOVED_TO|IN_DELETE_SELF|IN_MOVE_SELF)<0){close(fd);fd=-1;}
 return fd;
}
/* Preserve the animation cadence, but never sleep through a ready handoff.
 * Watch before checking the markers so a create/check/poll race cannot lose it.
 * Unrelated files (including our frame rename) do not restart the deadline. */
static void wait_handoff(int fd,double delay) {
 double deadline=seconds()+delay;
 while(!handoff_ready()) {
  double remaining=deadline-seconds();if(remaining<=0)return;
  if(fd<0){
   struct timespec pause={(time_t)remaining,(long)((remaining-floor(remaining))*1e9)};
   while(nanosleep(&pause,&pause)&&errno==EINTR&&!stopping){}
   return;
  }
  struct pollfd event={fd,POLLIN,0};
  int result=poll(&event,1,(int)ceil(remaining*1000));
  if(result<0){if(errno!=EINTR)fd=-1;continue;}
  if(event.revents&POLLIN){char buffer[4096];while(read(fd,buffer,sizeof(buffer))>0){}}
  if(event.revents&(POLLERR|POLLHUP|POLLNVAL))fd=-1;
 }
}
#endif
static int display(int continuous) {
 int fd=open("/dev/fb0",O_RDWR|O_CLOEXEC);if(fd<0)return 1;
 struct fb_var_screeninfo v;struct fb_fix_screeninfo f;
 if(ioctl(fd,FBIOGET_VSCREENINFO,&v)||ioctl(fd,FBIOGET_FSCREENINFO,&f)||v.bits_per_pixel!=32||v.red.length!=8||v.green.length!=8||v.blue.length!=8||v.xres!=W||v.yres!=H||f.line_length<(v.xoffset+W)*4||f.smem_len<(v.yoffset+H)*f.line_length){close(fd);return 1;}
 uint8_t *fb=mmap(NULL,f.smem_len,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
 if(fb==MAP_FAILED){close(fd);return 1;}
 console_mode(KD_GRAPHICS);signal(SIGTERM,stop_signal);signal(SIGINT,stop_signal);
#ifndef SLOT_SPLASH_INIT
 int watch=continuous?watch_handoff():-1;
#endif
 double started=seconds(),last=started;float shown=(float)percentage();int previous=-1;
 do {
  if(continuous&&(exists("handoff")||exists("failed")))break;
  double now=seconds();int real=percentage();if(real>100)real=100;
  float target=(float)real;shown=fmaxf(shown,shown+(target-shown)*fminf(1,(float)(now-last)*12));last=now;
  scene(shown,real,now,1);
  for(unsigned y=0;y<H;y++){
   uint32_t *out=(uint32_t *)(fb+(y+v.yoffset)*f.line_length+v.xoffset*4);
   for(unsigned x=0;x<W;x++){
    uint8_t *p=pixels+(y*W+x)*4;
    out[x]=((uint32_t)(p[0]>>(8-v.red.length))<<v.red.offset)|((uint32_t)(p[1]>>(8-v.green.length))<<v.green.offset)|((uint32_t)(p[2]>>(8-v.blue.length))<<v.blue.offset);
   }
  }
  if(previous<0)stamp("events/splash-first-frame");
  if(real!=previous){scene((float)real,real,0,1);if(save(ROOT"/frame.tmp",0)==0)rename(ROOT"/frame.tmp",ROOT"/frame.rgba");previous=real;}
  if(!continuous)break;
#ifdef SLOT_SPLASH_INIT
  struct timespec pause={0,66666666};nanosleep(&pause,NULL);
#else
  wait_handoff(watch,1.0/15);
#endif
 }while(!stopping&&seconds()-started<45);
#ifndef SLOT_SPLASH_INIT
 if(watch>=0)close(watch);
#endif
 munmap(fb,f.smem_len);close(fd);
 if(continuous){touch("renderer.stopped");if(!exists("handoff"))console_mode(KD_TEXT);}
 return 0;
}
#endif
int main(int argc,char **argv) {
 if(argc==4&&(!strcmp(argv[1],"--rgba")||!strcmp(argv[1],"--ppm"))){char *end;long p=strtol(argv[2],&end,10);if(*end||p<0||p>100)return 2;scene((float)p,(int)p,0,1);return save(argv[3],!strcmp(argv[1],"--ppm"))?1:0;}
 mkdir(ROOT,0700);mkdir(ROOT"/events",0700);
 if(argc==2&&!strcmp(argv[1],"--stream"))return stream_marks();
 if(argc==3&&(!strcmp(argv[1],"--event")||!strcmp(argv[1],"--begin"))){
  return record(argv[1],argv[2]);
 }
 if(argc==2&&!strcmp(argv[1],"--percent")){printf("%d\n",percentage());return 0;}
#ifdef __linux__
 if(argc==2&&!strcmp(argv[1],"--error")){touch("failed");return console_mode(KD_TEXT)?1:0;}
 if(argc==2&&!strcmp(argv[1],"--run"))return display(1);
 if(argc==2&&!strcmp(argv[1],"--draw"))return display(0);
#endif
 fprintf(stderr,"Use --draw, --run, --event ID, --begin ID, --stream, --error, --percent, --rgba P FILE or --ppm P FILE\n");return 2;
}
