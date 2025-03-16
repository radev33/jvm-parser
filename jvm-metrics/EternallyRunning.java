public class EternallyRunning {
    public static void main(String[] args) throws InterruptedException {
        while (true){
            Thread.sleep(1000);
            Thread.yield();
        }
    }
}
