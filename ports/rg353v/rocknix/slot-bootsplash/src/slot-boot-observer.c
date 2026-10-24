// SPDX-License-Identifier: GPL-2.0-or-later
// Match the Python observer's milestone policy without spawning systemctl.
#define _GNU_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <systemd/sd-bus.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "plan.h"
#include "observer-plan.h"
_Static_assert(STEP_COUNT == INIT_COUNT + SERVICE_COUNT + FRONTEND_COUNT, "Shared boot plan mismatch");

#define ROOT "/run/slot-boot"
struct state {
    char active[32], load[32], result[32];
    bool condition;
    uint64_t condition_at, exit_at;
};
static volatile sig_atomic_t stopping;
static bool dirty[SERVICE_COUNT];
static unsigned service_job_events;
static int job_removed(sd_bus_message *message, void *data, sd_bus_error *error) {
    (void)data; (void)error;
    uint32_t id;
    const char *path, *unit, *result;
    if(sd_bus_message_read(message,"uoss",&id,&path,&unit,&result)<0) return 0;
    for(size_t i=0;i<SERVICE_COUNT;++i)
        for(size_t j=0;services[i].units[j];++j)
            if(!strcmp(unit,services[i].units[j])) {dirty[i]=true;++service_job_events;}
    return 0;
}
static void stop(int sig) { (void)sig; stopping = 1; }
static bool exists(const char *name) {
    char p[512]; int n=snprintf(p, sizeof(p), ROOT "/%s", name);
    if(n<0 || (size_t)n>=sizeof(p)) return false;
    return access(p, F_OK) == 0;
}
static double seconds(void) {
    struct timespec t; clock_gettime(CLOCK_BOOTTIME, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static int outcome(const struct state *s, bool optional, bool settled) {
    if (!strcmp(s->active, "active")) return 1;
    if (!strcmp(s->active, "failed")) return 2;
    if (!strcmp(s->load, "masked") || !strcmp(s->load, "not-found")) return optional ? 3 : 0;
    if (!strcmp(s->active, "inactive")) {
        if (!s->condition && s->condition_at) return 3;
        if (s->exit_at) return !strcmp(s->result, "success") ? 1 : 2;
        if (optional && settled) return 3;
    }
    return 0;
}
static int open_manager(sd_bus **out) {
    // Like root systemctl, avoid a dependency on the system bus daemon.
    sd_bus *bus=NULL;
    int r=sd_bus_new(&bus);
    if(r>=0)r=sd_bus_set_address(bus,"unix:path=/run/systemd/private");
    if(r>=0)r=sd_bus_start(bus);
    if(r>=0) {
        struct ucred cred;
        socklen_t size=sizeof(cred);
        int fd=sd_bus_get_fd(bus);
        if(fd>=0 && !getsockopt(fd,SOL_SOCKET,SO_PEERCRED,&cred,&size) &&
           size==sizeof(cred) && cred.uid==0) {
            *out=bus;fputs("Slot boot observer: manager transport private\n",stderr);return 0;
        }
    }
    sd_bus_close_unref(bus);
    return sd_bus_open_system(out);
}
static int get_text(sd_bus *bus, const char *path, const char *interface,
                    const char *property, char dest[32], sd_bus_error *error) {
    char *value=NULL;
    int r=sd_bus_get_property_string(bus,"org.freedesktop.systemd1",path,interface,property,error,&value);
    if(r>=0)snprintf(dest,32,"%s",value);
    free(value);return r;
}
static int query(sd_bus *bus, const char *name, struct state *s) {
    const char *unit="org.freedesktop.systemd1.Unit";
    const char *service="org.freedesktop.systemd1.Service";
    char *path=NULL;
    sd_bus_message *reply=NULL;
    sd_bus_error error=SD_BUS_ERROR_NULL;
    memset(s,0,sizeof(*s));s->condition=true;strcpy(s->result,"success");
    int r=sd_bus_path_encode("/org/freedesktop/systemd1/unit",name,&path);
    if(r>=0)r=get_text(bus,path,unit,"ActiveState",s->active,&error);
    if(r<0 && sd_bus_error_has_name(&error,"org.freedesktop.DBus.Error.UnknownObject")) {
        sd_bus_error_free(&error);
        r=sd_bus_call_method(bus,"org.freedesktop.systemd1","/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager","LoadUnit",&error,&reply,"s",name);
        if(r<0 && (sd_bus_error_has_name(&error,"org.freedesktop.systemd1.NoSuchUnit") ||
                   sd_bus_error_has_name(&error,"org.freedesktop.systemd1.UnitMasked"))) {
            strcpy(s->load,sd_bus_error_has_name(&error,"org.freedesktop.systemd1.UnitMasked")?"masked":"not-found");
            strcpy(s->active,"inactive");r=0;goto done;
        }
        if(r>=0)r=get_text(bus,path,unit,"ActiveState",s->active,&error);
    }
    if(r<0 || !strcmp(s->active,"active") || !strcmp(s->active,"failed"))goto done;
    r=get_text(bus,path,unit,"LoadState",s->load,NULL);
    if(r<0 || strcmp(s->active,"inactive") || !strcmp(s->load,"masked") || !strcmp(s->load,"not-found"))goto done;
    int condition=1;
    if(sd_bus_get_property_trivial(bus,"org.freedesktop.systemd1",path,unit,"ConditionResult",NULL,'b',&condition)>=0)
        s->condition=condition;
    sd_bus_get_property_trivial(bus,"org.freedesktop.systemd1",path,unit,"ConditionTimestampMonotonic",NULL,'t',&s->condition_at);
    if(!s->condition && s->condition_at)goto done;
    size_t n=strlen(name);
    if(n>=8 && !strcmp(name+n-8,".service")) {
        sd_bus_get_property_trivial(bus,"org.freedesktop.systemd1",path,service,"ExecMainExitTimestampMonotonic",NULL,'t',&s->exit_at);
        if(s->exit_at)get_text(bus,path,service,"Result",s->result,NULL);
    }
done:
    free(path);sd_bus_error_free(&error);sd_bus_message_unref(reply);
    return r<0?r:0;
}
static void mark(const char *id) {
    char p[256]; snprintf(p,sizeof(p),ROOT "/events/service-%s",id);
    int fd = open(p,O_WRONLY|O_CREAT|O_CLOEXEC,0600);
    if (fd >= 0) close(fd);
}
static void renderer_stop(pid_t child) {
    if (child <= 0) return;
    if (waitpid(child,NULL,WNOHANG) != 0) return;
    kill(child,SIGTERM);
    for (int i=0; i<100; ++i) {
        if (waitpid(child,NULL,WNOHANG) != 0) return;
        nanosleep(&(struct timespec){0,10000000},NULL);
    }
    kill(child,SIGKILL); waitpid(child,NULL,0);
}
static int self_test(void) {
    struct state s = {.active="active"};
    if (outcome(&s,false,false)!=1) return 1;
    strcpy(s.active,"failed"); if (outcome(&s,false,false)!=2) return 1;
    strcpy(s.active,"inactive");strcpy(s.load,"masked");
    if (outcome(&s,true,false)!=3 || outcome(&s,false,false)!=0) return 1;
    strcpy(s.load,"loaded");s.condition_at=1;
    if (outcome(&s,false,false)!=3) return 1;
    s.condition=true;s.condition_at=0;s.exit_at=1;strcpy(s.result,"success");
    if (outcome(&s,false,false)!=1) return 1;
    strcpy(s.result,"exit-code");if (outcome(&s,false,false)!=2) return 1;
    s.exit_at=0;
    if (outcome(&s,true,false)!=0 || outcome(&s,true,true)!=3) return 1;
    puts("PASS native milestone outcomes"); return 0;
}
int main(int argc, char **argv) {
    if (argc==2 && !strcmp(argv[1],"--self-test")) return self_test();
    if (argc==2 && !strcmp(argv[1],"--subscribe-check")) {
        sd_bus *test=NULL;
        int r=open_manager(&test);
        if(r>=0)r=sd_bus_call_method(test,"org.freedesktop.systemd1","/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager","Subscribe",NULL,NULL,NULL);
        sd_bus_close_unref(test);
        if(r>=0)puts("PASS manager subscription");
        return r<0?1:0;
    }
    bool snapshot = argc==2 && !strcmp(argv[1],"--snapshot");
    if (argc!=1 && !snapshot) return 2;
    if (!snapshot && exists("frontend.displayed")) return 0;
    signal(SIGTERM,stop);signal(SIGINT,stop);
    FILE *log = stdout;
    pid_t renderer = -1;
    if (!snapshot) {
        mkdir(ROOT,0700);mkdir(ROOT "/events",0700);
        log = fopen(ROOT "/progress.jsonl","a");
        if (!log) return 1;
        setvbuf(log,NULL,_IOLBF,0);
        fprintf(log,"{\"event\":\"plan\",\"total\":%zu,\"init_steps\":%u,\"service_groups\":%zu,\"frontend_steps\":%u,\"observer\":\"native\"}\n",
            STEP_COUNT,INIT_COUNT,SERVICE_COUNT,FRONTEND_COUNT);
        renderer = fork();
        if (!renderer) { execl("/usr/bin/slot-splash","slot-splash","--run",(char *)NULL);_exit(127); }
        if (renderer < 0) { fclose(log);return 1; }
    }
    sd_bus *bus = NULL;
    sd_bus_slot *event_slot = NULL;
    bool finished[SERVICE_COUNT]; memset(finished,0,sizeof(finished));
    for(size_t i=0;i<SERVICE_COUNT;++i)dirty[i]=true;
    double deadline = seconds()+40;
    double refresh_at=0;
    bool failed = false;
    const char *labels[] = {"pending","ready","failed","skipped"};
    while (!stopping && seconds()<deadline) {
        bool displayed=!snapshot && exists("frontend.displayed");
        if (!snapshot && exists("failed")) {failed=true;break;}
        if (!bus && open_manager(&bus)>=0) {
            sd_bus_set_method_call_timeout(bus,200000);
            if(!snapshot && sd_bus_match_signal(bus,&event_slot,NULL,"/org/freedesktop/systemd1",
                "org.freedesktop.systemd1.Manager","JobRemoved",job_removed,NULL)>=0 &&
                sd_bus_call_method(bus,"org.freedesktop.systemd1","/org/freedesktop/systemd1",
                "org.freedesktop.systemd1.Manager","Subscribe",NULL,NULL,NULL)>=0)
                fputs("Slot boot observer: job events enabled\n",stderr);
            refresh_at=0;
        }
        if (bus) {
            // Drain event bursts once; unrelated jobs do not re-query our units.
            for(int i=0;i<512 && sd_bus_process(bus,NULL)>0;++i) {}
            if(displayed || seconds()>=refresh_at) {
                for(size_t i=0;i<SERVICE_COUNT;++i)if(!finished[i])dirty[i]=true;
                refresh_at=seconds()+1;
            }
            for (size_t i=0;i<SERVICE_COUNT;++i) {
                if (finished[i] || !dirty[i]) continue;
                if (services[i].after>=0 && !finished[services[i].after]) continue;
                dirty[i]=false;
                int combined=1;
                for (size_t j=0;services[i].units[j];++j) {
                    struct state state;
                    int r=query(bus,services[i].units[j],&state);
                    int value=r<0?0:outcome(&state,services[i].optional,services[i].after>=0);
                    if (!value) {combined=0;break;}
                    if (value==2 || (combined!=2 && value==3)) combined=value;
                }
                if (combined || snapshot) {
                    if (!snapshot) {finished[i]=true;mark(services[i].id);}
                    for(size_t k=0;k<SERVICE_COUNT;++k)
                        if(services[k].after==(int)i)dirty[k]=true;
                    fprintf(log,"{\"event\":\"%s\",\"result\":\"%s\",\"at_boottime\":%.9f}\n",services[i].id,labels[combined],seconds());
                }
            }
        }
        if (snapshot) {sd_bus_slot_unref(event_slot);sd_bus_unref(bus);return bus?0:1;}
        if (displayed) break;
        if (waitpid(renderer,NULL,WNOHANG)==renderer && !exists("handoff")) {failed=true;break;}
        nanosleep(&(struct timespec){0,150000000},NULL);
    }
    if (!exists("frontend.displayed") && (stopping || seconds()>=deadline)) failed=true;
    sd_bus_slot_unref(event_slot);sd_bus_unref(bus);
    renderer_stop(renderer);
    if (failed && !exists("handoff")) {
        int fd=open(ROOT "/failed",O_WRONLY|O_CREAT|O_CLOEXEC,0600);if(fd>=0)close(fd);
        pid_t p=fork();if(!p){execl("/usr/bin/slot-splash","slot-splash","--error",(char*)NULL);_exit(127);}if(p>0)waitpid(p,NULL,0);
    }
    size_t done=0;
    for(size_t i=0;i<STEP_COUNT;++i){char p[256];snprintf(p,sizeof(p),"events/%s",steps[i]);done+=exists(p);}
    fprintf(log,"{\"event\":\"finished\",\"completed\":%zu,\"total\":%zu,\"percent\":%zu,\"frontend_displayed\":%s,\"service_job_events\":%u}\n",done,STEP_COUNT,100*done/STEP_COUNT,exists("frontend.displayed")?"true":"false",service_job_events);
    fclose(log);
    unlink(ROOT "/frame.rgba");unlink(ROOT "/frame.tmp");
    // Python export/profiling now starts only after screen ownership has passed.
    execl("/usr/bin/slot-boot-progress","slot-boot-progress","--finish",(char*)NULL);
    return 1;
}
