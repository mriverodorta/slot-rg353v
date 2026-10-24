// Exercise the production wait without opening the framebuffer or console.
#define main slot_splash_main
#include "../src/slot-splash.c"
#undef main
int main(int argc,char **argv) {
 mkdir(ROOT,0700);
 signal(SIGTERM,stop_signal);
 int fd=watch_handoff();
 if(argc==2&&!strcmp(argv[1],"fallback")){if(fd>=0)close(fd);fd=-1;}
 else if(fd<0)return 2;
 touch("wait.ready");
 wait_handoff(fd,fd<0?.1:5);
 if(fd>=0)close(fd);
 printf("%d\n",handoff_ready());
 return 0;
}
