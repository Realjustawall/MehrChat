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
        final Messenger[] remote={null};final String[] result={""};final IOException[] error={null};
        final ParcelFileDescriptor[] pipe=ParcelFileDescriptor.createPipe(),output=ParcelFileDescriptor.createPipe();
        ServiceConnection connection=new ServiceConnection(){
            public void onServiceConnected(ComponentName name,IBinder binder){remote[0]=new Messenger(binder);ready.countDown();}
            public void onServiceDisconnected(ComponentName name){completed.countDown();ready.countDown();}
        };
        boolean bound=false;
        try {
            bound=context.bindService(new Intent(context,PreviewService.class),connection,Context.BIND_AUTO_CREATE);
            if(!bound||!ready.await(5,TimeUnit.SECONDS)||remote[0]==null)throw new IOException("Isolated service binding failed");
            Message request=Message.obtain(null,1);Bundle args=new Bundle();args.putParcelable("input",pipe[0]);args.putParcelable("output",output[1]);args.putString("kind",kind);request.setData(args);remote[0].send(request);
            pipe[0].close();output[1].close();
            // Isolated UIDs cannot reliably send a Binder callback into an app
            // on current Android. Return bounded bytes through the granted FD.
            Thread reader=new Thread(()->{
                try(InputStream stream=new ParcelFileDescriptor.AutoCloseInputStream(output[0])){
                    ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;
                    while((n=stream.read(buffer))!=-1){if(bytes.size()+n>272048)throw new IOException("Preview output limit");bytes.write(buffer,0,n);}
                    result[0]=new String(bytes.toByteArray(),java.nio.charset.StandardCharsets.UTF_8);
                }catch(IOException failure){error[0]=failure;}finally{completed.countDown();}
            });reader.setDaemon(true);reader.start();
            Thread writer=new Thread(()->{try(OutputStream stream=new ParcelFileDescriptor.AutoCloseOutputStream(pipe[1])){stream.write(raw);}catch(IOException ignored){}});writer.setDaemon(true);writer.start();
            if(!completed.await(10,TimeUnit.SECONDS))throw new IOException("Isolated preview timeout");
            if(error[0]!=null)throw error[0];
            return result[0];
        }finally {
            if(remote[0]!=null)try{remote[0].send(Message.obtain(null,99));}catch(Exception ignored){}
            if(bound)context.unbindService(connection);
            try{pipe[0].close();}catch(IOException ignored){}try{pipe[1].close();}catch(IOException ignored){}
            try{output[0].close();}catch(IOException ignored){}try{output[1].close();}catch(IOException ignored){}
        }
    }
}
