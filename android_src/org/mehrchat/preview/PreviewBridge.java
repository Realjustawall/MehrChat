package org.mehrchat.preview;
import android.content.*;
import android.os.*;
import java.io.*;
import java.util.concurrent.*;
/** Blocking API called only from a Python background thread. */
public final class PreviewBridge {
    public static String render(Context context,byte[] raw,String kind)throws Exception {
        if(raw.length>4*1024*1024)throw new IOException();
        final CountDownLatch ready=new CountDownLatch(1),completed=new CountDownLatch(1);
        final Messenger[] remote={null};final String[] result={""};
        final ParcelFileDescriptor[] pipe=ParcelFileDescriptor.createPipe();
        Messenger reply=new Messenger(new Handler(Looper.getMainLooper()){
            @Override public void handleMessage(Message message){result[0]=message.getData().getString("json","");completed.countDown();}
        });
        ServiceConnection connection=new ServiceConnection(){
            public void onServiceConnected(ComponentName name,IBinder binder){remote[0]=new Messenger(binder);ready.countDown();}
            public void onServiceDisconnected(ComponentName name){completed.countDown();ready.countDown();}
        };
        boolean bound=context.bindService(new Intent(context,PreviewService.class),connection,Context.BIND_AUTO_CREATE);
        try {
            if(!bound||!ready.await(5,TimeUnit.SECONDS)||remote[0]==null)throw new IOException();
            Message request=Message.obtain(null,1);Bundle args=new Bundle();args.putParcelable("input",pipe[0]);args.putString("kind",kind);request.setData(args);request.replyTo=reply;remote[0].send(request);
            Thread writer=new Thread(()->{try(OutputStream stream=new ParcelFileDescriptor.AutoCloseOutputStream(pipe[1])){stream.write(raw);}catch(IOException ignored){}});writer.setDaemon(true);writer.start();
            if(!completed.await(10,TimeUnit.SECONDS))throw new IOException();
            return result[0];
        }finally {
            if(remote[0]!=null)try{remote[0].send(Message.obtain(null,99));}catch(Exception ignored){}
            if(bound)context.unbindService(connection);
            try{pipe[0].close();}catch(IOException ignored){}try{pipe[1].close();}catch(IOException ignored){}
        }
    }
}
