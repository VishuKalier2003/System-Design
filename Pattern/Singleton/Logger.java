package Singleton;

import java.util.*;
import Reader.FastReader;

public class Logger {
    public static class Switches {
        public static Map<Integer, Singleton> singletonMap = new HashMap<>();
        public static int idx = 1;

        public static void createNewInstance(int value) {
            System.out.println("======================================================");
            System.out.println("              A NEW INSTANCE CREATED                  ");
            System.out.println("======================================================");
            singletonMap.put(idx++, Singleton.getInstance(value));
        }

        public static void getAllInstances() {
            for(Map.Entry<Integer, Singleton> entry : singletonMap.entrySet())
                System.out.println("Instance number : "+entry.getKey()+" - Instance hash code : "+entry.getValue().getHashCode() + ", "+entry.getValue().value());
        }

        public static boolean checkTwoInstances(int index1, int index2) {
            System.out.println("======================================================");
            System.out.println("              TWO INSTANCES WILL BE CHECKED           ");
            System.out.println("======================================================");
            return singletonMap.get(index1) == singletonMap.get(index2);
        }
    }
    public static void main(String[] args) {
        FastReader fastReader = new FastReader();
        int n = -1;
        System.out.println("======================================================");
        System.out.println("              SINGLETON CONTROL CALLS                 ");
        System.out.println(" This is the control test calls for Singleton pattern ");
        System.out.println(" 0- Terminate the call");
        System.out.println(" 1- Create a NEW INSTANCE");
        System.out.println(" 2- Get ALL INSTANCES");
        System.out.println(" 3- Compare tw INSTANCES to check there is actually a single instance");
        System.out.println(" 4- Write in the file");
        System.out.println("======================================================");
        while(n != 0) {
            n = fastReader.nextInt();
            switch(n) {
                case 0 -> {System.out.println("CALL WILL END NOW"); break;}
                case 1 -> {Switches.createNewInstance(fastReader.nextInt()); break;}
                case 2 -> {Switches.getAllInstances(); break;}
                case 3 -> {System.out.println("Are two taken instances same ? "+Switches.checkTwoInstances(fastReader.nextInt(), fastReader.nextInt())); break;}
                case 4 -> {Switches.singletonMap.get(1).log(fastReader.nextLine());}
                default -> System.out.println("Wrong n value entered");
            }
        }
        for(Singleton instance : Switches.singletonMap.values())
            instance.close();
    }
}
